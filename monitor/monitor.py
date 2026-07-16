"""
monitor.py
----------
The fraud monitoring service - the incremental version. This does NOT
rescan transaction history. It:

  1. Fetches only transactions the feeder has inserted but nobody has
     scored yet (a naturally bounded query - WHERE scored_at IS NULL).
  2. Looks up just the sender/receiver profiles touched by THIS batch
     (O(1) PK lookups into user_profiles, not a table scan).
  3. Pulls a small bounded window of each involved sender's recent history
     (for the 1h/6h/24h velocity features) - an indexed range query, cheap
     regardless of total history size.
  4. Computes features causally within the batch, scores with the trained
     ensemble - XGBoost + Isolation Forest + Local Outlier Factor + the
     rule engine (see ml/ensemble.py) - writes flags/alerts back, updates
     the touched profiles, and PREVENTS further fraud from any account a
     hard rule (or a high-confidence ensemble score) blocks: it's
     suspended (users.kyc_status -> 'suspended'), so feeder/feeder.py
     stops selecting it as a sender on subsequent batches.

Prerequisite: run database/init_profiles.py once after loading historical
data / training, so every user already has a baseline profile "learned"
from history before the monitor starts watching live traffic.

Run the feeder and the monitor at the same time (two terminals):
    Terminal 1: python feeder/feeder.py
    Terminal 2: python monitor/monitor.py

Usage:
    python monitor.py                  # poll forever
    python monitor.py --cycles 5        # poll 5 times then stop
    python monitor.py --once            # score whatever is pending, then exit
"""

import os
import sys
import time
import argparse
import datetime as dt
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (_ROOT, os.path.join(_ROOT, "ml"), os.path.join(_ROOT, "database")):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    import psycopg2
except ImportError as e:
    print(f"Missing dependency: {e}. Install with:\n    pip install psycopg2-binary")
    sys.exit(1)

import config
from online_features import compute_batch_features
from profile_store import fetch_profiles, upsert_profiles, fetch_seen_pairs, insert_new_pairs, fetch_recent_sender_history
from export_transactions_from_db import BASE_QUERY
from write_alerts_to_db import write_alerts, suspend_users
from ensemble import load_ensemble_components, score_ensemble

PENDING_QUERY = BASE_QUERY.format(where_clause="WHERE scored_at IS NULL")


def score_cycle(conn, components):
    pending_df = pd.read_sql(PENDING_QUERY, conn)
    if pending_df.empty:
        return 0, 0, 0

    sender_ids = pending_df["nameOrig"].unique().tolist()
    receiver_ids = pending_df["nameDest"].unique().tolist()
    all_users = list(set(sender_ids) | set(receiver_ids))

    # --- Bounded lookups: only touches users/pairs/recent-history involved
    # --- in THIS batch, never the full transaction table. -------------------
    profiles = fetch_profiles(conn, all_users)

    pairs_in_batch = list(zip(pending_df["nameOrig"], pending_df["nameDest"]))
    seen_pairs = fetch_seen_pairs(conn, pairs_in_batch)

    batch_min_step = float(pending_df["step"].min())
    max_window = max(config.VELOCITY_WINDOWS_HOURS)
    recent_rows = fetch_recent_sender_history(
        conn, sender_ids,
        earliest_step=batch_min_step - max_window,
        upper_step_exclusive=batch_min_step,
    )
    recent_history = {}
    for sender_id, step in recent_rows:
        recent_history.setdefault(sender_id, []).append(float(step))

    # --- Compute causal features incrementally, updating profiles in place --
    feat_df, new_pairs = compute_batch_features(pending_df, profiles, seen_pairs, recent_history)

    dummies = pd.get_dummies(feat_df["txn_type"], prefix="txn_type")
    feat_df = pd.concat([feat_df, dummies], axis=1)
    for c in components["feature_cols"]:
        if c not in feat_df.columns:
            feat_df[c] = 0

    scored_df = score_ensemble(feat_df, components)

    # --- Persist: updated profiles, new pairs, and the scores/alerts themselves
    upsert_profiles(conn, profiles)
    insert_new_pairs(conn, new_pairs)
    n_updated, n_alerts = write_alerts(
        conn, scored_df[["txn_id", "fraud_probability", "flagged", "blocked", "block_reason"]], config.MODEL_VERSION
    )

    # --- Prevention: freeze any sender whose transaction just got hard-
    # --- blocked, so the feeder stops sending on their behalf. --------------
    blocked_senders = scored_df.loc[scored_df["blocked"], "sender_id"].unique().tolist()
    n_suspended = suspend_users(conn, blocked_senders)

    top_alerts = scored_df[scored_df["flagged"] == 1].sort_values("fraud_probability", ascending=False).head(5)
    if len(top_alerts):
        print("  Top new alerts this cycle:")
        for r in top_alerts.itertuples():
            tag = "  [BLOCKED + ACCOUNT SUSPENDED]" if r.blocked else ""
            print(f"    txn_id={r.txn_id}  {r.sender_id} -> {r.receiver_id}  "
                  f"amount={r.amount:.2f}  prob={r.fraud_probability:.3f}{tag}")

    return n_updated, n_alerts, n_suspended


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", default=config.DB_DSN)
    parser.add_argument("--interval", type=float, default=config.MONITOR_POLL_INTERVAL_SECONDS)
    parser.add_argument("--cycles", type=int, default=None, help="stop after N cycles (default: run forever)")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.once:
        args.cycles = 1

    try:
        components = load_ensemble_components()
    except ImportError as e:
        print(f"Missing dependency: {e}. Install with:\n    pip install xgboost joblib")
        sys.exit(1)
    except FileNotFoundError as e:
        print(e)
        sys.exit(1)

    conn = psycopg2.connect(args.dsn)

    print(f"Monitor starting (incremental mode - no history rescans). "
          f"Polling every {args.interval}s, alert threshold={config.ALERT_THRESHOLD}, "
          f"block threshold={config.BLOCK_THRESHOLD}. Ctrl+C to stop.")
    print("NOTE: run database/init_profiles.py once before starting this, "
          "so users already have a learned baseline from history.")
    try:
        cycle = 0
        while args.cycles is None or cycle < args.cycles:
            n_updated, n_alerts, n_suspended = score_cycle(conn, components)
            ts = dt.datetime.now().strftime("%H:%M:%S")
            if n_updated:
                print(f"[{ts}] Scored {n_updated} new transactions, {n_alerts} flagged as fraud risk, "
                      f"{n_suspended} accounts newly suspended.")
            else:
                print(f"[{ts}] No new transactions to score.")

            cycle += 1
            if args.cycles is None or cycle < args.cycles:
                time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nMonitor stopped.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
