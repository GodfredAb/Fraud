"""
rebuild_historical.py
----------------------
One command that puts the system in "trained on history, ready to watch
live traffic" state, instead of three manual steps run in the right order
by hand:

  1. Reset the database and seed 500 subscribers across all 10 Ghana
     regions (database/seed_generator.py).
  2. Generate a large, organic transaction HISTORY - a realistic fraud
     rate (config default: 2%, not an inflated test rate), the same five
     behavioral fraud patterns feeder.py uses live, spread over ~2 years
     of calendar time - and load it as ALREADY RESOLVED history: scored,
     flagged/approved, but never re-suspending an account over old,
     closed cases, and never touching fraud_alerts (that queue is for
     LIVE alerts only, so the demo starts with it empty).
  3. Compute every user's behavioral baseline from that history in one
     pass (what database/init_profiles.py does - inlined here so it runs
     automatically as part of this rebuild instead of a separate command
     someone has to remember).
  4. Retrain the ensemble (ml/train.py) on the same historical data.

After this finishes, start the live demo with no further setup:
    Terminal 1: python feeder/feeder.py
    Terminal 2: python monitor/monitor.py
Neither retrains anything or re-learns profiles - both just run against
the model artifacts and baselines this script already wrote.

The calendar span (--years) is a presentation-layer mapping only
(txn_timestamp / scored_at, for a database that reads like real multi-year
history when browsed) - it does NOT change the step-based hour convention
every feature/rule/velocity-window is built on (config.TIMESTAMP_IS_DATETIME
stays False). See historical_timestamps() below.

Usage:
    python database/rebuild_historical.py --dsn "$DSN"
"""

import _pathfix  # noqa: F401
import os
import sys
import subprocess
import argparse
import datetime as dt

import numpy as np
import pandas as pd

import config
from seed_generator import (
    generate_users, generate_devices_and_subscribers, generate_locations, generate_transactions,
)
from build_database import (
    apply_schema, insert_users, insert_devices, insert_subscribers, insert_links, insert_locations,
)
from export_transactions_from_db import BASE_QUERY
from init_profiles import compute_final_profiles
from profile_store import upsert_profiles, insert_new_pairs

sys.path.insert(0, os.path.join(config.BASE_DIR, "ml"))
from feature_engineering import load_and_standardize  # noqa: E402


def historical_timestamps(steps, years_span: float, end_at: dt.datetime):
    steps = np.asarray(steps, dtype=float)
    max_step = max(float(steps.max()), 1.0)
    hours_per_step = (years_span * 365.0 * 24.0) / max_step
    return [end_at - dt.timedelta(hours=(max_step - s) * hours_per_step) for s in steps]


def insert_historical_transactions(conn, df, user_to_imei, timestamps):
    from psycopg2.extras import execute_values
    rng = np.random.RandomState(7)

    rows = []
    for r, ts in zip(df.itertuples(index=False), timestamps):
        is_fraud = bool(r.isFraud)
        # Already-resolved history needs a probability column that looks
        # like a model's output, not a hand-set label - natural-looking
        # scores per class, not exactly 0/1.
        prob = rng.uniform(0.82, 0.97) if is_fraud else rng.uniform(0.01, 0.12)
        rows.append((
            int(r.step), ts, r.type, float(r.amount),
            r.nameOrig, user_to_imei.get(r.nameOrig),
            float(r.oldbalanceOrg), float(r.newbalanceOrig),
            r.nameDest, user_to_imei.get(r.nameDest),
            float(r.oldbalanceDest), float(r.newbalanceDest),
            is_fraud, round(float(prob), 5), is_fraud,
            False,
            ("historical case, reviewed and confirmed" if is_fraud else None),
            (not is_fraud),
            "historical-ground-truth", ts,
        ))

    with conn.cursor() as cur:
        execute_values(cur, """
            INSERT INTO transactions (
                txn_step, txn_timestamp, txn_type, amount,
                sender_user_id, sender_imei, sender_balance_old, sender_balance_new,
                receiver_user_id, receiver_imei, receiver_balance_old, receiver_balance_new,
                is_fraud, fraud_probability, flagged, blocked, block_reason,
                auto_approved, model_version, scored_at
            ) VALUES %s
        """, rows, page_size=2000)
    conn.commit()
    print(f"  loaded {len(rows)} historical transactions "
          f"(already resolved - scored_at is set, so monitor.py's pending queue starts empty).")


def main():
    import psycopg2

    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", default=config.DB_DSN)
    parser.add_argument("--n-users", type=int, default=500)
    parser.add_argument("--n-transactions", type=int, default=120000)
    parser.add_argument("--fraud-rate", type=float, default=0.02)
    parser.add_argument("--years", type=float, default=2.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--csv-out", default=os.path.join(config.BASE_DIR, "data", "historical.csv"))
    parser.add_argument("--skip-train", action="store_true", help="load data/profiles but don't retrain the ensemble")
    args = parser.parse_args()

    conn = psycopg2.connect(args.dsn)
    try:
        print("1/5 Resetting schema...")
        apply_schema(conn, fresh=True)

        print(f"2/5 Seeding {args.n_users} subscribers across all 10 Ghana regions...")
        users = generate_users(args.n_users, seed=args.seed)
        insert_users(conn, users)
        devices, subscribers = generate_devices_and_subscribers(users, seed=args.seed)
        imei_to_device_id = insert_devices(conn, devices)
        user_to_subscriber_id = insert_subscribers(conn, subscribers)
        insert_links(conn, devices, imei_to_device_id, user_to_subscriber_id)
        locations = generate_locations(users, seed=args.seed)
        insert_locations(conn, locations)
        user_to_imei = {d["user_id"]: d["imei"] for d in devices}
        print(f"  {len(users)} users, {len(devices)} devices, {len(locations)} location pings.")

        print(f"3/5 Generating {args.n_transactions:,} historical transactions "
              f"({args.fraud_rate * 100:.1f}% organic fraud rate, ~{args.years} simulated years)...")
        user_ids = [u["user_id"] for u in users]
        txn_df = generate_transactions(user_ids, n=args.n_transactions, fraud_rate=args.fraud_rate, seed=args.seed)
        os.makedirs(os.path.dirname(args.csv_out), exist_ok=True)
        txn_df.to_csv(args.csv_out, index=False)
        n_fraud = int(txn_df["isFraud"].sum())
        print(f"  {len(txn_df):,} transactions generated ({n_fraud:,} fraud, "
              f"{n_fraud / len(txn_df) * 100:.2f}%) - saved to {args.csv_out}")

        end_at = dt.datetime.now() - dt.timedelta(hours=1)
        timestamps = historical_timestamps(txn_df["step"].values, args.years, end_at)
        insert_historical_transactions(conn, txn_df, user_to_imei, timestamps)

        print("4/5 Computing behavioral baselines from history (init_profiles, run automatically)...")
        raw_df = pd.read_sql(BASE_QUERY.format(where_clause=""), conn)
        std_df = load_and_standardize(raw_df)
        profiles, pairs = compute_final_profiles(std_df)
        upsert_profiles(conn, profiles)
        insert_new_pairs(conn, pairs)
        print(f"  baselines computed for {len(profiles)} users, {len(pairs)} sender-receiver pairs. "
              f"monitor.py will not need to rescan this history again.")
    finally:
        conn.close()

    if args.skip_train:
        print("5/5 Skipped (--skip-train). Run `python ml/train.py "
              f"{args.csv_out}` manually when ready.")
        return

    print("5/5 Retraining the ensemble on this historical data...")
    train_py = os.path.join(config.BASE_DIR, "ml", "train.py")
    subprocess.run([sys.executable, train_py, args.csv_out], check=True)

    print("\nDone. Database holds resolved history only - monitor.py's pending "
          "queue is empty and ready for live traffic. Start the demo with:\n"
          "  Terminal 1: python feeder/feeder.py --dsn \"$DSN\"\n"
          "  Terminal 2: python monitor/monitor.py --dsn \"$DSN\"")


if __name__ == "__main__":
    main()
