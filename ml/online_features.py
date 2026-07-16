"""
online_features.py
--------------------
Computes the SAME features as ml/feature_engineering.py's training-time
pipeline, but incrementally: using each user's stored profile (current
mean/std/max/count/etc.) instead of recomputing from full history.

This is the piece that makes the monitor cheap: processing a batch of N
new transactions costs O(N) plus a couple of bounded, indexed DB lookups
- never O(total history size).

Feature definitions here MUST match feature_engineering.py's definitions,
or the model will see a different distribution at inference time than it
learned at training time. If you change one, change the other.
"""

import math
import datetime as dt
import numpy as np
import pandas as pd

import config
from feature_engineering import add_transaction_level_features, load_and_standardize
from profile_store import welford_update, DEFAULT_PROFILE


def _hours_between(t1, t2):
    if config.TIMESTAMP_IS_DATETIME:
        return (t1 - t2).total_seconds() / 3600.0
    return float(t1 - t2)  # already in "step" hour units


def compute_batch_features(raw_batch_df, profiles: dict, seen_pairs: set, recent_history: dict):
    """
    raw_batch_df: DataFrame of NEW transactions only (raw column names, e.g.
                  straight from a DB export), NOT yet standardized.
    profiles:     dict user_id -> profile dict (from profile_store.fetch_profiles),
                  mutated in place as the batch is processed.
    seen_pairs:   set of (sender_id, receiver_id) tuples already seen before
                  this batch, mutated in place as new pairs appear.
    recent_history: dict sender_id -> list of past timestamps (float hours or
                  datetime), seeded from profile_store.fetch_recent_sender_history,
                  mutated in place so multiple txns from the same sender within
                  one batch still see each other for velocity counts.

    Returns: (feature_df, new_pairs) where feature_df has one row per input
    transaction (same order) with all FEATURE_COLUMNS populated, and
    new_pairs is the list of (sender_id, receiver_id) tuples first seen in
    this batch (to be persisted via profile_store.insert_new_pairs).
    """
    df = load_and_standardize(raw_batch_df)          # column renaming + stable timestamp sort, no state
    df = add_transaction_level_features(df)          # row-wise, no state needed
    # (no re-sort here: load_and_standardize already produced a stable,
    # timestamp-ordered frame with ties broken the same way the offline
    # training pipeline breaks them - re-sorting again with a non-stable
    # sort would silently reorder tied-timestamp transactions differently
    # between training and inference.)

    windows = config.VELOCITY_WINDOWS_HOURS
    default_gap = config.TIME_SINCE_LAST_TXN_DEFAULT_HOURS

    out_rows = []
    new_pairs = []

    for row in df.itertuples(index=False):
        sender, receiver = row.sender_id, row.receiver_id
        ps = profiles.setdefault(sender, dict(DEFAULT_PROFILE))
        pr = profiles.setdefault(receiver, dict(DEFAULT_PROFILE))

        n = ps["sender_txn_count"]
        mean = ps["sender_amount_mean"]
        m2 = ps["sender_amount_m2"]
        std = math.sqrt(m2 / (n - 1)) if n > 1 else 0.0
        cummax = ps["sender_amount_max"] if ps["sender_amount_max"] is not None else 0.0

        zscore = (row.amount - mean) / std if std > 0 else 0.0

        if ps["sender_last_txn_step"] is not None:
            gap = _hours_between(row.timestamp, ps["sender_last_txn_step"])
        else:
            gap = default_gap

        pair = (sender, receiver)
        is_new_counterparty = int(pair not in seen_pairs)

        hist = recent_history.setdefault(sender, [])
        velocity_counts = {}
        for w in windows:
            velocity_counts[f"user_txn_count_last_{w}"] = sum(
                1 for t in hist if row.timestamp - w <= t < row.timestamp
            )

        out_rows.append({
            "txn_id": row.txn_id,
            "timestamp": row.timestamp,
            "sender_id": sender,
            "receiver_id": receiver,
            "amount": row.amount,
            "txn_type": row.txn_type,
            "amount_log": row.amount_log,
            "sender_balance_delta": row.sender_balance_delta,
            "sender_balance_error": row.sender_balance_error,
            "receiver_balance_delta": row.receiver_balance_delta,
            "receiver_balance_error": row.receiver_balance_error,
            "sender_emptied_account": row.sender_emptied_account,
            "sender_insufficient_funds_flag": row.sender_insufficient_funds_flag,
            "is_cash_out_or_transfer": row.is_cash_out_or_transfer,
            "hour_of_day": row.hour_of_day,
            "is_night_txn": row.is_night_txn,
            "user_txn_count_so_far": n,
            "user_amount_cummean": mean,
            "user_amount_cumstd": std,
            "user_amount_cummax": cummax,
            "amount_zscore_vs_self": zscore,
            "time_since_last_txn": gap,
            **velocity_counts,
            "user_distinct_receivers_so_far": ps["sender_distinct_receivers"],
            "is_new_counterparty": is_new_counterparty,
            "receiver_incoming_count_so_far": pr["receiver_incoming_count"],
            "receiver_distinct_senders_so_far": pr["receiver_distinct_senders"],
            "receiver_fanin_ratio": pr["receiver_distinct_senders"] / (pr["receiver_incoming_count"] + 1),
        })

        # --- Update state for the NEXT transaction (causal) -----------------
        new_n, new_mean, new_m2 = welford_update(n, mean, m2, row.amount)
        ps["sender_txn_count"] = new_n
        ps["sender_amount_mean"] = new_mean
        ps["sender_amount_m2"] = new_m2
        ps["sender_amount_max"] = max(cummax, row.amount)
        ps["sender_last_txn_step"] = row.timestamp
        hist.append(row.timestamp)

        pr["receiver_incoming_count"] += 1

        if is_new_counterparty:
            ps["sender_distinct_receivers"] += 1
            pr["receiver_distinct_senders"] += 1
            seen_pairs.add(pair)
            new_pairs.append(pair)

    return pd.DataFrame(out_rows), new_pairs
