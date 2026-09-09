"""
feeder.py
---------
The "feeder program": simulates the mobile money network continuously
sending new transactions into the database, the way a real telco's
transaction-processing system would. This is the source of "traffic" that
monitor.py watches and scores.

Picks real existing users/devices from the database (so foreign keys are
valid) and generates plausible new transactions between them. A small
share of traffic (config.FEEDER_FRAUD_INJECTION_RATE, ~5% by default -
in the neighborhood of published mobile money fraud incidence, not an
inflated test rate) follows one of five real fraud behavior patterns -
see FRAUD_SUBTYPES below - the same patterns present in the historical
data the model was trained on, so the live feed and the training
distribution describe the same underlying population:

  - drain:                 a single sudden large account-draining transaction
  - sim_swap_drain:        the sender's SIM gets re-paired to a brand new
                            device, then immediately drained
  - structuring:           several individually-moderate transactions to
                            different receivers in quick succession that sum
                            to a large total - evades a single-transaction cutoff
  - rapid_fanout:          several transactions to brand-new receivers in
                            quick succession - spraying funds across
                            multiple (possibly mule) accounts
  - dormant_reactivation:  an account that's gone quiet the longest suddenly
                            moves a large amount - a common account-takeover
                            pattern

This is also where PREVENTION becomes visible end to end: monitor.py
suspends (kyc_status -> 'suspended') the sender of any hard-blocked
transaction, and this feeder re-checks who's suspended before every batch
and refuses to originate further transactions from those accounts - a
real transaction-processing system would enforce the same check at
authorization time, not just log an alert after the fact.

Usage:
    # run forever, a batch of transactions every few seconds
    python feeder.py

    # run a fixed number of cycles then stop (useful for demos/tests)
    python feeder.py --cycles 5 --batch-size 10 --interval 2
"""

import _pathfix  # noqa: F401
import sys
import time
import random
import argparse
import datetime as dt
import numpy as np

import config

TXN_TYPES = ["CASH_IN", "CASH_OUT", "PAYMENT", "TRANSFER", "DEBIT"]
TXN_TYPE_WEIGHTS = [0.25, 0.25, 0.30, 0.15, 0.05]


def fetch_user_pool(conn):
    """Users + their current device IMEI + their most recent known balance."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT s.user_id, d.imei
            FROM subscriber_device_links l
            JOIN subscribers s ON s.subscriber_id = l.subscriber_id
            JOIN devices d ON d.device_id = l.device_id
            WHERE l.is_current = TRUE
        """)
        user_to_imei = dict(cur.fetchall())

        cur.execute("SELECT MAX(txn_step) FROM transactions")
        max_step = cur.fetchone()[0] or 0

        # Last known balance per user (as sender's new balance, fallback random)
        cur.execute("""
            SELECT DISTINCT ON (sender_user_id) sender_user_id, sender_balance_new
            FROM transactions
            WHERE sender_user_id IS NOT NULL
            ORDER BY sender_user_id, txn_timestamp DESC
        """)
        last_balance = dict(cur.fetchall())

    return user_to_imei, max_step, last_balance


def fetch_suspended_users(conn):
    """Accounts monitor.py has frozen (kyc_status='suspended') after a
    hard-blocked transaction - re-checked before every batch so
    prevention takes effect within one feeder cycle of the monitor acting
    on it, not just at process startup."""
    with conn.cursor() as cur:
        cur.execute("SELECT user_id FROM users WHERE kyc_status = 'suspended'")
        return {r[0] for r in cur.fetchall()}


def swap_device(conn, user_id, rng):
    """Simulates a SIM swap / device change for one user: retires their
    current subscriber_device_links row and pairs their SIM with a brand
    new device (new random IMEI). Returns the new IMEI. This is what gives
    ml/rules.py's device_change_then_large_txn rule something real to
    catch - without an actual change event, sender_imei never differs
    from a user's stored profile and the rule can never fire.

    Retries on an IMEI collision (devices.imei is UNIQUE): re-running this
    demo with the same or overlapping --seed values across separate
    processes can land the shared rng on the same 15-digit sequence twice
    - a real, observed collision, not a one-in-10^15 fluke, since it's
    deterministic reuse of the same RNG stream rather than independent
    randomness. An uncaught UniqueViolation previously killed the whole
    feeder run before it inserted anything."""
    import psycopg2

    with conn.cursor() as cur:
        cur.execute("""
            SELECT l.subscriber_id FROM subscriber_device_links l
            JOIN subscribers s ON s.subscriber_id = l.subscriber_id
            WHERE s.user_id = %s AND l.is_current = TRUE
        """, (user_id,))
        row = cur.fetchone()
        if row is None:
            return None
        subscriber_id = row[0]

    for _attempt in range(5):
        new_imei = "".join(str(rng.randint(0, 9)) for _ in range(15))
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE subscriber_device_links SET is_current = FALSE, last_seen_at = now()
                    WHERE subscriber_id = %s AND is_current = TRUE
                """, (subscriber_id,))
                cur.execute("""
                    INSERT INTO devices (imei, manufacturer, model)
                    VALUES (%s, 'Unknown', 'Unknown') RETURNING device_id
                """, (new_imei,))
                device_id = cur.fetchone()[0]
                cur.execute("""
                    INSERT INTO subscriber_device_links (subscriber_id, device_id, is_current)
                    VALUES (%s, %s, TRUE)
                """, (subscriber_id, device_id))
            conn.commit()
            return new_imei
        except psycopg2.errors.UniqueViolation:
            conn.rollback()
    return None


def fetch_most_dormant_sender(conn, eligible_senders):
    """Picks whichever eligible sender has gone longest since their last
    transaction - used to inject a realistic dormant-account-reactivation
    pattern (ml/rules.py's dormant_account_reactivated rule) instead of a
    uniformly random pick, since a randomly-chosen sender is rarely
    actually dormant. Deliberately excludes senders with NO transaction
    history at all (a plain INNER-JOIN-shaped query via GROUP BY, not a
    LEFT JOIN with a sentinel): the rule requires user_txn_count_so_far > 0
    - a never-sent user always fails that guard, so picking one here would
    just waste the injection. Returns (sender_id, last_step), or None
    (caller falls back to a random pick) if no eligible sender has ever
    sent anything yet."""
    if not eligible_senders:
        return None
    with conn.cursor() as cur:
        cur.execute("""
            SELECT sender_user_id, MAX(txn_step) AS last_step
            FROM transactions
            WHERE sender_user_id = ANY(%s)
            GROUP BY sender_user_id
            ORDER BY last_step ASC
            LIMIT 1
        """, (eligible_senders,))
        row = cur.fetchone()
        return (row[0], row[1]) if row else None


def _make_row(step, txn_type, amount, sender, sender_old, sender_new, receiver, receiver_old, user_to_imei, is_fraud):
    return (
        step, dt.datetime.now(), txn_type, round(amount, 2),
        sender, user_to_imei.get(sender), round(sender_old, 2), round(sender_new, 2),
        receiver, user_to_imei.get(receiver), round(receiver_old, 2), round(receiver_old + amount, 2),
        is_fraud,  # ground truth, for demo evaluation only - a real feed wouldn't know this yet
    )


def _drain_pattern(sender, receiver, sender_old, step, user_to_imei, rng):
    """Classic pattern: one large transfer/cash-out that empties the account."""
    txn_type = rng.choice(["TRANSFER", "CASH_OUT"])
    amount = max(sender_old * rng.uniform(0.85, 1.0), rng.uniform(2000, 8000))
    sender_new = max(sender_old - amount, 0.0)
    row = _make_row(step, txn_type, amount, sender, sender_old, sender_new, receiver, rng.uniform(100, 4000), user_to_imei, True)
    return [row], sender_new


def _multi_receiver_pattern(sender, user_ids, sender_old, step, user_to_imei, amount_fn, rng):
    """Shared shape for structuring and rapid_fanout: several TRANSFERs from
    one sender to DIFFERENT receivers, 1 step apart (close enough together
    to land in each other's 6h window - see ml/rules.py's velocity_6h_cutoff
    comment for why 1 step apart, not the same step)."""
    k = rng.randint(3, 5)
    others = [u for u in user_ids if u != sender]
    receivers = rng.sample(others, min(k, len(others)))
    rows = []
    bal = sender_old
    for i, receiver in enumerate(receivers):
        amount = amount_fn(bal, rng)
        new_bal = max(bal - amount, 0.0)
        rows.append(_make_row(step + i, "TRANSFER", amount, sender, bal, new_bal, receiver, rng.uniform(100, 4000), user_to_imei, True))
        bal = new_bal
    return rows, bal


def _structuring_pattern(sender, user_ids, sender_old, step, user_to_imei, rng):
    """Several individually-moderate transactions that sum to a large
    total - evades a single-transaction amount cutoff."""
    def amount_fn(bal, rng):
        amt = rng.uniform(300, 900)
        return min(amt, bal) if bal > 0 else amt
    return _multi_receiver_pattern(sender, user_ids, sender_old, step, user_to_imei, amount_fn, rng)


def _rapid_fanout_pattern(sender, user_ids, sender_old, step, user_to_imei, rng):
    """Several transactions to brand-new receivers in quick succession -
    spraying funds across multiple (possibly mule) accounts."""
    def amount_fn(bal, rng):
        amt = float(np.random.exponential(250))
        return min(amt, bal) if bal > 0 else amt
    return _multi_receiver_pattern(sender, user_ids, sender_old, step, user_to_imei, amount_fn, rng)


FRAUD_SUBTYPES = ("drain", "sim_swap_drain", "structuring", "rapid_fanout", "dormant_reactivation")
FRAUD_SUBTYPE_WEIGHTS = (0.30, 0.20, 0.20, 0.20, 0.10)


def generate_batch(conn, user_ids, eligible_senders, user_to_imei, last_balance, step, batch_size, fraud_rate, rng):
    """eligible_senders: user_ids minus anyone currently suspended - a
    suspended account can still receive (e.g. incoming refunds/investigation
    holds don't have to bounce), but can no longer originate a transaction.
    Multi-row fraud subtypes (structuring, rapid_fanout) can push total rows
    per batch above batch_size - the loop below counts ITERATIONS, not rows,
    same as it always has, so a batch that rolls one of those patterns simply
    ends up a little larger than usual."""
    rows = []
    for _ in range(batch_size):
        if len(eligible_senders) < 1 or len(user_ids) < 2:
            break

        is_injected_fraud = rng.random() < fraud_rate
        subtype = rng.choices(FRAUD_SUBTYPES, weights=FRAUD_SUBTYPE_WEIGHTS, k=1)[0] if is_injected_fraud else None

        if subtype == "dormant_reactivation":
            found = fetch_most_dormant_sender(conn, eligible_senders)
            if found:
                sender, _ = found  # the numeric last_step doesn't matter here - see row_step below
            else:
                sender = rng.choice(eligible_senders)
                subtype = "drain"  # no one has ever sent yet - just an ordinary drain
        else:
            sender = rng.choice(eligible_senders)
        sender_old = float(last_balance.get(sender, rng.uniform(200, 5000)))

        if subtype == "sim_swap_drain":
            # SIM-swap fraud: sender's SIM gets paired with a brand new
            # device, then immediately drained - the swap-then-drain
            # playbook device_change_then_large_txn is meant to catch.
            new_imei = swap_device(conn, sender, rng)
            if new_imei:
                user_to_imei[sender] = new_imei
            receiver = rng.choice([u for u in user_ids if u != sender])
            new_rows, sender_new = _drain_pattern(sender, receiver, sender_old, step, user_to_imei, rng)
        elif subtype == "dormant_reactivation":
            # Same shape as drain, but the whole simulation clock jumps
            # forward by 340-500 steps for this one event, guaranteeing a
            # gap of at least that size vs this sender's real last
            # transaction (dormant_last_step <= the current step, since
            # it's in the past) - real dormancy this long can't occur
            # organically here (100 users picked near-uniformly every
            # transaction means no one goes unselected for anywhere near
            # 336 steps by chance), so the injection forces it directly.
            # Advancing the SHARED clock (not just this row's own step)
            # matters: if only this row were aged forward while the clock
            # stayed behind, a later ordinary pick of this same sender
            # could land a smaller step in between (or even one indicating
            # a negative time gap once scored) - fast-forwarding the whole
            # clock rules that out for every sender, not just this one.
            receiver = rng.choice([u for u in user_ids if u != sender])
            row_step = round(step + rng.uniform(340, 500))
            new_rows, sender_new = _drain_pattern(sender, receiver, sender_old, row_step, user_to_imei, rng)
        elif subtype == "drain":
            receiver = rng.choice([u for u in user_ids if u != sender])
            new_rows, sender_new = _drain_pattern(sender, receiver, sender_old, step, user_to_imei, rng)
        elif subtype == "structuring":
            new_rows, sender_new = _structuring_pattern(sender, user_ids, sender_old, step, user_to_imei, rng)
        elif subtype == "rapid_fanout":
            new_rows, sender_new = _rapid_fanout_pattern(sender, user_ids, sender_old, step, user_to_imei, rng)
        else:
            receiver = rng.choice([u for u in user_ids if u != sender])
            txn_type = rng.choices(TXN_TYPES, weights=TXN_TYPE_WEIGHTS, k=1)[0]
            amount = float(np.random.exponential(180))
            amount = min(amount, sender_old) if sender_old > 0 else amount
            sender_new = max(sender_old - amount, 0.0)
            new_rows = [_make_row(step, txn_type, amount, sender, sender_old, sender_new, receiver, rng.uniform(100, 4000), user_to_imei, False)]

        last_balance[sender] = sender_new
        rows.extend(new_rows)
        step = row_step + 1 if subtype == "dormant_reactivation" else step + len(new_rows)
    return rows, step


def insert_batch(conn, rows):
    from psycopg2.extras import execute_values
    with conn.cursor() as cur:
        execute_values(cur, """
            INSERT INTO transactions (
                txn_step, txn_timestamp, txn_type, amount,
                sender_user_id, sender_imei, sender_balance_old, sender_balance_new,
                receiver_user_id, receiver_imei, receiver_balance_old, receiver_balance_new,
                is_fraud
            ) VALUES %s
        """, rows)
    conn.commit()


def main():
    try:
        import psycopg2
    except ImportError:
        print("psycopg2 is not installed. Install it with:\n    pip install psycopg2-binary")
        sys.exit(1)

    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", default=config.DB_DSN)
    parser.add_argument("--batch-size", type=int, default=config.FEEDER_BATCH_SIZE)
    parser.add_argument("--interval", type=float, default=config.FEEDER_INTERVAL_SECONDS)
    parser.add_argument("--fraud-rate", type=float, default=config.FEEDER_FRAUD_INJECTION_RATE)
    parser.add_argument("--cycles", type=int, default=None, help="stop after N cycles (default: run forever)")
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    conn = psycopg2.connect(args.dsn)

    try:
        user_to_imei, step, last_balance = fetch_user_pool(conn)
        user_ids = list(user_to_imei.keys())
        if len(user_ids) < 2:
            print("Fewer than 2 users found in the database. Run database/build_database.py first.")
            sys.exit(1)

        print(f"Feeder starting. {len(user_ids)} subscribers on the network. "
              f"Batch size={args.batch_size}, interval={args.interval}s.")

        cycle = 0
        while args.cycles is None or cycle < args.cycles:
            suspended = fetch_suspended_users(conn)
            eligible_senders = [u for u in user_ids if u not in suspended]

            rows, step = generate_batch(
                conn, user_ids, eligible_senders, user_to_imei, last_balance, step,
                args.batch_size, args.fraud_rate, rng,
            )
            if rows:
                insert_batch(conn, rows)
            n_fraud = sum(r[-1] for r in rows)
            fraud_note = f", {n_fraud} matching a known fraud pattern" if n_fraud else ""
            suspended_note = f", {len(suspended)} accounts currently suspended" if suspended else ""
            print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] "
                  f"Processed {len(rows)} transactions{fraud_note}{suspended_note}.")

            cycle += 1
            if args.cycles is None or cycle < args.cycles:
                time.sleep(args.interval)

        print("Feeder finished.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
