"""
build_database.py
------------------
Applies schema.sql, seeds synthetic users/devices/subscribers (IMSI) and
their location history, then loads an initial batch of transactions
(generating data/synthetic.csv itself, via seed_generator.generate_transactions,
if that file doesn't already exist).

Usage:
    python database/build_database.py --transactions ../data/synthetic.csv --fresh
"""

import _pathfix  # noqa: F401
import os
import sys
import argparse

import pandas as pd

import config
from seed_generator import (
    generate_users, generate_devices_and_subscribers, generate_locations, generate_transactions,
)


def apply_schema(conn, fresh: bool):
    schema_path = os.path.join(config.BASE_DIR, "database", "schema.sql")
    with open(schema_path) as f:
        schema_sql = f.read()
    with conn.cursor() as cur:
        if fresh:
            cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        cur.execute(schema_sql)
    conn.commit()


def insert_users(conn, users):
    from psycopg2.extras import execute_values
    rows = [
        (u["user_id"], u["full_name"], u["national_id"], u["date_of_birth"],
         u["gender"], u["msisdn"], u["kyc_status"], u["registration_date"])
        for u in users
    ]
    with conn.cursor() as cur:
        execute_values(cur, """
            INSERT INTO users (user_id, full_name, national_id, date_of_birth,
                                gender, msisdn, kyc_status, registration_date)
            VALUES %s
        """, rows)
    conn.commit()


def insert_devices(conn, devices):
    """Returns {imei: device_id} using the DB-assigned SERIAL ids."""
    from psycopg2.extras import execute_values
    rows = [(d["imei"], d["manufacturer"], d["model"]) for d in devices]
    with conn.cursor() as cur:
        result = execute_values(cur, """
            INSERT INTO devices (imei, manufacturer, model) VALUES %s
            RETURNING device_id, imei
        """, rows, fetch=True)
    conn.commit()
    return {imei: device_id for device_id, imei in result}


def insert_subscribers(conn, subscribers):
    """Returns {user_id: subscriber_id} using the DB-assigned SERIAL ids."""
    from psycopg2.extras import execute_values
    rows = [(s["imsi"], s["msisdn"], s["user_id"]) for s in subscribers]
    with conn.cursor() as cur:
        result = execute_values(cur, """
            INSERT INTO subscribers (imsi, msisdn, user_id) VALUES %s
            RETURNING subscriber_id, user_id
        """, rows, fetch=True)
    conn.commit()
    return {user_id: subscriber_id for subscriber_id, user_id in result}


def insert_links(conn, devices, imei_to_device_id, user_to_subscriber_id):
    from psycopg2.extras import execute_values
    rows = [
        (user_to_subscriber_id[d["user_id"]], imei_to_device_id[d["imei"]], True)
        for d in devices
    ]
    with conn.cursor() as cur:
        execute_values(cur, """
            INSERT INTO subscriber_device_links (subscriber_id, device_id, is_current)
            VALUES %s
        """, rows)
    conn.commit()


def insert_locations(conn, locations):
    from psycopg2.extras import execute_values
    rows = [
        (l["user_id"], l["latitude"], l["longitude"], l["recorded_at"], l["source"])
        for l in locations
    ]
    with conn.cursor() as cur:
        execute_values(cur, """
            INSERT INTO user_locations (user_id, latitude, longitude, recorded_at, source)
            VALUES %s
        """, rows)
    conn.commit()


def load_transactions_csv(conn, path, user_to_imei):
    from psycopg2.extras import execute_values
    c = config.COLS
    df = pd.read_csv(path)

    rows = []
    for r in df.itertuples(index=False):
        sender = getattr(r, c["sender"])
        receiver = getattr(r, c["receiver"])
        is_fraud = bool(getattr(r, c["label"])) if c["label"] and c["label"] in df.columns else False
        rows.append((
            int(getattr(r, c["step"])), None, getattr(r, c["type"]), float(getattr(r, c["amount"])),
            sender, user_to_imei.get(sender),
            float(getattr(r, c["sender_old_balance"])), float(getattr(r, c["sender_new_balance"])),
            receiver, user_to_imei.get(receiver),
            float(getattr(r, c["receiver_old_balance"])), float(getattr(r, c["receiver_new_balance"])),
            is_fraud,
        ))

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
    print(f"Loaded {len(rows)} transactions.")


def main():
    try:
        import psycopg2
    except ImportError:
        print("psycopg2 is not installed. Install it with:\n    pip install psycopg2-binary")
        sys.exit(1)

    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", default=config.DB_DSN)
    parser.add_argument("--transactions", default=os.path.join(config.BASE_DIR, "data", "synthetic.csv"))
    parser.add_argument("--n-users", type=int, default=500)
    parser.add_argument("--n-transactions", type=int, default=2000)
    parser.add_argument("--fresh", action="store_true", help="drop and recreate all tables first")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    conn = psycopg2.connect(args.dsn)
    try:
        print("Applying schema" + (" (--fresh: dropping existing tables first)..." if args.fresh else "..."))
        apply_schema(conn, args.fresh)

        print(f"Generating {args.n_users} synthetic users, one device + one SIM each, plus location history...")
        users = generate_users(args.n_users, seed=args.seed)
        insert_users(conn, users)

        devices, subscribers = generate_devices_and_subscribers(users, seed=args.seed)
        imei_to_device_id = insert_devices(conn, devices)
        user_to_subscriber_id = insert_subscribers(conn, subscribers)
        insert_links(conn, devices, imei_to_device_id, user_to_subscriber_id)

        locations = generate_locations(users, seed=args.seed)
        insert_locations(conn, locations)

        if not os.path.exists(args.transactions):
            print(f"{args.transactions} not found - generating {args.n_transactions} synthetic transactions...")
            txn_df = generate_transactions(
                [u["user_id"] for u in users], n=args.n_transactions, seed=args.seed,
            )
            os.makedirs(os.path.dirname(args.transactions), exist_ok=True)
            txn_df.to_csv(args.transactions, index=False)

        user_to_imei = {d["user_id"]: d["imei"] for d in devices}
        load_transactions_csv(conn, args.transactions, user_to_imei)

        print("Database build complete.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
