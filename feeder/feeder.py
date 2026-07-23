"""
feeder.py
---------
The "feeder program": simulates the mobile money network continuously
sending new transactions into the database, the way a real telco's
transaction-processing system would. This is the source of "traffic" that
monitor.py watches and scores.

Picks real existing users/devices from the database (so foreign keys are
valid) and generates plausible new transactions between them, occasionally
injecting a deliberately fraud-like transaction - either a sudden large
account-draining amount, or a SIM-swap pattern (the sender's SIM gets
re-paired to a brand new device, then immediately drained) - so you can
verify the monitor actually catches both.

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
    from a user's stored profile and the rule can never fire."""
    new_imei = "".join(str(rng.randint(0, 9)) for _ in range(15))
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


def generate_batch(conn, user_ids, eligible_senders, user_to_imei, last_balance, step, batch_size, fraud_rate, rng):
    """eligible_senders: user_ids minus anyone currently suspended - a
    suspended account can still receive (e.g. incoming refunds/investigation
    holds don't have to bounce), but can no longer originate a transaction."""
    rows = []
    for _ in range(batch_size):
        if len(eligible_senders) < 1 or len(user_ids) < 2:
            break
        sender = rng.choice(eligible_senders)
        receiver = rng.choice([u for u in user_ids if u != sender])
        txn_type = rng.choices(TXN_TYPES, weights=TXN_TYPE_WEIGHTS, k=1)[0]

        is_injected_fraud = rng.random() < fraud_rate
        sender_old = float(last_balance.get(sender, rng.uniform(200, 5000)))

        if is_injected_fraud and rng.random() < 0.5:
            # SIM-swap fraud: sender's SIM gets paired with a brand new
            # device, then immediately drained - the swap-then-drain
            # playbook device_change_then_large_txn is meant to catch.
            new_imei = swap_device(conn, sender, rng)
            if new_imei:
                user_to_imei[sender] = new_imei
            txn_type = rng.choice(["TRANSFER", "CASH_OUT"])
            amount = max(sender_old * rng.uniform(0.85, 1.0), rng.uniform(2000, 8000))
            sender_new = max(sender_old - amount, 0.0)
        elif is_injected_fraud:
            # Classic drain pattern: large transfer/cash-out that empties the account
            txn_type = rng.choice(["TRANSFER", "CASH_OUT"])
            amount = max(sender_old * rng.uniform(0.85, 1.0), rng.uniform(2000, 8000))
            sender_new = max(sender_old - amount, 0.0)
        else:
            amount = float(np.random.exponential(180))
            amount = min(amount, sender_old) if sender_old > 0 else amount
            sender_new = max(sender_old - amount, 0.0)

        receiver_old = rng.uniform(100, 4000)
        receiver_new = receiver_old + amount

        last_balance[sender] = sender_new

        rows.append((
            step, dt.datetime.now(), txn_type, round(amount, 2),
            sender, user_to_imei.get(sender), round(sender_old, 2), round(sender_new, 2),
            receiver, user_to_imei.get(receiver), round(receiver_old, 2), round(receiver_new, 2),
            is_injected_fraud,  # ground truth, for demo evaluation only - a real feed wouldn't know this yet
        ))
        step += 1
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

        print(f"Feeder starting. {len(user_ids)} users available. "
              f"Batch size={args.batch_size}, interval={args.interval}s, "
              f"fraud injection rate={args.fraud_rate}.")

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
            suspended_note = f", {len(suspended)} accounts suspended (excluded as senders)" if suspended else ""
            print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] "
                  f"Inserted {len(rows)} transactions "
                  f"({n_fraud} deliberately fraud-like for testing){suspended_note}.")

            cycle += 1
            if args.cycles is None or cycle < args.cycles:
                time.sleep(args.interval)

        print("Feeder finished.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
