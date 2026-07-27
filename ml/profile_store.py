"""
profile_store.py
-----------------
Manages each user's running behavioral profile (user_profiles table) and
sender->receiver pair history (user_pair_history table). This is the piece
that lets the monitor score new traffic without ever rescanning the full
transaction history:

  - Historical "learning" happens ONCE, in database/init_profiles.py, which
    reads all past transactions and computes each user's final cumulative
    state (mean/std/max spend, txn count, distinct counterparties, etc.)
  - After that, every new transaction just reads its sender's and
    receiver's current profile row (a PK lookup), computes features off of
    it, scores it, and updates that one row (Welford's online algorithm -
    no need to re-read past amounts to update a running mean/variance).

Everything here is O(number of users touched by the current batch), never
O(total transaction history).
"""

import datetime as dt


DEFAULT_PROFILE = {
    "sender_txn_count": 0,
    "sender_amount_mean": 0.0,
    "sender_amount_m2": 0.0,
    "sender_amount_max": None,
    "sender_last_txn_step": None,
    "sender_distinct_receivers": 0,
    "receiver_incoming_count": 0,
    "receiver_distinct_senders": 0,
    # SIM-swap / device-cloning detection: the IMEI seen on this sender's
    # last transaction, and when their device last changed (None = never
    # observed a change) - see ml/online_features.py.
    "sender_last_imei": None,
    "sender_last_device_change_step": None,
}

PROFILE_COLUMNS = list(DEFAULT_PROFILE.keys())


def welford_update(count, mean, m2, new_value):
    """Online update of running mean/variance given one new observation.
    Returns (new_count, new_mean, new_m2). Std = sqrt(m2 / (count-1))."""
    count += 1
    delta = new_value - mean
    mean += delta / count
    delta2 = new_value - mean
    m2 += delta * delta2
    return count, mean, m2


def fetch_profiles(conn, user_ids):
    """Fetch current profile rows for exactly these users (PK lookup - fast
    regardless of table size). Missing users get DEFAULT_PROFILE (i.e. this
    is their first-ever transaction)."""
    if not user_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT user_id, {", ".join(PROFILE_COLUMNS)}
            FROM user_profiles WHERE user_id = ANY(%s)
        """, (list(set(user_ids)),))
        rows = cur.fetchall()

    profiles = {uid: dict(DEFAULT_PROFILE) for uid in user_ids}
    for row in rows:
        uid = row[0]
        profiles[uid] = dict(zip(PROFILE_COLUMNS, row[1:]))
    return profiles


def upsert_profiles(conn, profiles: dict):
    """Bulk write updated profile rows back. `profiles` maps user_id -> dict
    of PROFILE_COLUMNS values."""
    from psycopg2.extras import execute_values
    if not profiles:
        return
    rows = [
        (
            uid,
            p["sender_txn_count"], p["sender_amount_mean"], p["sender_amount_m2"],
            p["sender_amount_max"], p["sender_last_txn_step"], p["sender_distinct_receivers"],
            p["receiver_incoming_count"], p["receiver_distinct_senders"],
            p["sender_last_imei"], p["sender_last_device_change_step"],
            dt.datetime.now(),
        )
        for uid, p in profiles.items()
    ]
    with conn.cursor() as cur:
        execute_values(cur, """
            INSERT INTO user_profiles (
                user_id, sender_txn_count, sender_amount_mean, sender_amount_m2,
                sender_amount_max, sender_last_txn_step, sender_distinct_receivers,
                receiver_incoming_count, receiver_distinct_senders,
                sender_last_imei, sender_last_device_change_step, updated_at
            ) VALUES %s
            ON CONFLICT (user_id) DO UPDATE SET
                sender_txn_count = EXCLUDED.sender_txn_count,
                sender_amount_mean = EXCLUDED.sender_amount_mean,
                sender_amount_m2 = EXCLUDED.sender_amount_m2,
                sender_amount_max = EXCLUDED.sender_amount_max,
                sender_last_txn_step = EXCLUDED.sender_last_txn_step,
                sender_distinct_receivers = EXCLUDED.sender_distinct_receivers,
                receiver_incoming_count = EXCLUDED.receiver_incoming_count,
                receiver_distinct_senders = EXCLUDED.receiver_distinct_senders,
                sender_last_imei = EXCLUDED.sender_last_imei,
                sender_last_device_change_step = EXCLUDED.sender_last_device_change_step,
                updated_at = EXCLUDED.updated_at
        """, rows)
    conn.commit()


def fetch_seen_pairs(conn, pairs):
    """Given a list of (sender_id, receiver_id) tuples, return the subset
    that already existed BEFORE this call (i.e. NOT new counterparties)."""
    if not pairs:
        return set()
    senders = [p[0] for p in pairs]
    receivers = [p[1] for p in pairs]
    with conn.cursor() as cur:
        # Note: (sender_id, receiver_id) = ANY(%s) with a Python list of
        # tuples doesn't work - psycopg2 has no way to adapt it to a
        # comparable composite-row array, so Postgres can't hash it
        # ("could not identify a hash function for type unknown"). Passing
        # the two columns as parallel arrays and unnesting them side by
        # side avoids that entirely.
        cur.execute("""
            SELECT uph.sender_id, uph.receiver_id
            FROM user_pair_history uph
            JOIN (
                SELECT unnest(%s::varchar[]) AS sender_id,
                       unnest(%s::varchar[]) AS receiver_id
            ) AS batch
              ON uph.sender_id = batch.sender_id AND uph.receiver_id = batch.receiver_id
        """, (senders, receivers))
        return set(cur.fetchall())


def insert_new_pairs(conn, pairs):
    from psycopg2.extras import execute_values
    if not pairs:
        return
    with conn.cursor() as cur:
        execute_values(cur, """
            INSERT INTO user_pair_history (sender_id, receiver_id)
            VALUES %s ON CONFLICT DO NOTHING
        """, [tuple(p) for p in pairs])
    conn.commit()


def fetch_recent_sender_history(conn, sender_ids, earliest_step: float, upper_step_exclusive: float):
    """Bounded query: only transactions from these specific senders with
    earliest_step <= txn_step < upper_step_exclusive (used to seed the
    1h/6h/24h velocity/amount-sum features - 'hours' meaning units of the
    txn_step counter, matching feature_engineering.py). amount is included
    alongside txn_step so online_features.py can compute windowed SUMS
    (structuring/smurfing detection: many sub-threshold transactions that
    add up to a large total), not just windowed COUNTS. The exclusive
    upper bound ensures this never re-reads any transaction that is part
    of the current pending batch itself (which the caller processes
    separately, in order, via online_features.compute_batch_features).
    Uses idx_txn_sender_step - a fast range scan, not a full-table scan,
    no matter how large the transactions table grows."""
    if not sender_ids:
        return []
    with conn.cursor() as cur:
        cur.execute("""
            SELECT sender_user_id, txn_step, amount
            FROM transactions
            WHERE sender_user_id = ANY(%s)
              AND txn_step >= %s AND txn_step < %s
            ORDER BY txn_step
        """, (list(set(sender_ids)), earliest_step, upper_step_exclusive))
        return cur.fetchall()
