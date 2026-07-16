"""
init_profiles.py
------------------
"The model studies the history" step. Reads ALL transactions currently in
the database ONE TIME, computes each user's final cumulative behavioral
state (average spend, spend variability, max spend, transaction count,
distinct counterparties, etc.), and writes it into user_profiles /
user_pair_history.

After this runs, monitor.py never needs to touch historical transactions
again - every new transaction just reads/updates its sender's and
receiver's single profile row.

Run this:
  - once, right after database/build_database.py's initial load
  - again whenever you want to deliberately re-baseline "normal" behavior
    (e.g. after a large re-training cycle) - safe to re-run, it recomputes
    from scratch and overwrites.

Usage:
    python init_profiles.py
"""

import _pathfix  # noqa: F401
import sys
import argparse
import numpy as np
import pandas as pd

import config
from export_transactions_from_db import BASE_QUERY
from profile_store import upsert_profiles, insert_new_pairs, PROFILE_COLUMNS

sys.path.insert(0, f"{config.BASE_DIR}/ml")
from feature_engineering import load_and_standardize  # noqa: E402


def compute_final_profiles(df: pd.DataFrame):
    """Vectorized (pandas groupby), computed ONCE over full history - not
    per-row, not per-cycle. Produces the exact final state each user's
    profile would be in if you'd updated it incrementally one transaction
    at a time, using Welford's algorithm-compatible sums."""
    profiles = {}

    sender_groups = df.groupby("sender_id")
    for uid, g in sender_groups:
        amounts = g["amount"].values
        n = len(amounts)
        mean = amounts.mean()
        m2 = float(((amounts - mean) ** 2).sum())  # Welford-compatible: variance = m2/(n-1)
        profiles.setdefault(uid, {}).update({
            "sender_txn_count": int(n),
            "sender_amount_mean": float(mean),
            "sender_amount_m2": m2,
            "sender_amount_max": float(amounts.max()),
            "sender_last_txn_step": float(g["timestamp"].max()),
            "sender_distinct_receivers": int(g["receiver_id"].nunique()),
        })

    receiver_groups = df.groupby("receiver_id")
    for uid, g in receiver_groups:
        profiles.setdefault(uid, {}).update({
            "receiver_incoming_count": int(len(g)),
            "receiver_distinct_senders": int(g["sender_id"].nunique()),
        })

    # Fill defaults for any field a user-only-as-sender or only-as-receiver is missing
    defaults = {
        "sender_txn_count": 0, "sender_amount_mean": 0.0, "sender_amount_m2": 0.0,
        "sender_amount_max": None, "sender_last_txn_step": None, "sender_distinct_receivers": 0,
        "receiver_incoming_count": 0, "receiver_distinct_senders": 0,
    }
    for uid, p in profiles.items():
        for k, v in defaults.items():
            p.setdefault(k, v)

    pair_first_seen = (
        df.groupby(["sender_id", "receiver_id"])["timestamp"].min().reset_index()
    )
    pairs = list(zip(pair_first_seen["sender_id"], pair_first_seen["receiver_id"]))

    return profiles, pairs


def main():
    try:
        import psycopg2
    except ImportError:
        print("psycopg2 is not installed. Install it with:\n    pip install psycopg2-binary")
        sys.exit(1)

    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", default=config.DB_DSN)
    args = parser.parse_args()

    conn = psycopg2.connect(args.dsn)
    try:
        print("Reading full transaction history (one-time scan)...")
        raw_df = pd.read_sql(BASE_QUERY.format(where_clause=""), conn)
        print(f"  {len(raw_df)} transactions found.")

        df = load_and_standardize(raw_df)
        profiles, pairs = compute_final_profiles(df)

        print(f"Computed profiles for {len(profiles)} users, {len(pairs)} sender-receiver pairs.")
        upsert_profiles(conn, profiles)
        insert_new_pairs(conn, pairs)
        print("Profiles and pair history written. The monitor can now score "
              "new traffic without ever re-reading this history.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
