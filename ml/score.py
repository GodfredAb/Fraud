"""
score.py
--------
One-off batch scoring: run the trained ensemble (XGBoost + Isolation Forest
+ Local Outlier Factor + the rule engine - see ml/ensemble.py) over a CSV of
transactions (e.g. a fresh export from the DB, or any held-out slice) and
write out just the flagged rows. This is the offline counterpart to
monitor/monitor.py's live incremental loop - useful for re-scoring a whole
file at once rather than watching a live feed.

Usage:
    python ml/score.py ../data/from_db.csv
    python ml/score.py ../data/from_db.csv --out ../outputs/flagged.csv
"""

import _pathfix  # noqa: F401
import os
import sys
import argparse
import numpy as np
import pandas as pd

import config
from feature_engineering import build_feature_table
from ensemble import load_ensemble_components, score_ensemble


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input_csv")
    parser.add_argument("--out", default=os.path.join(config.BASE_DIR, "outputs", "flagged_transactions.csv"))
    args = parser.parse_args()

    try:
        components = load_ensemble_components()
    except ImportError as e:
        print(f"Missing dependency: {e}. Install with:\n    pip install xgboost joblib")
        sys.exit(1)
    except FileNotFoundError as e:
        print(e)
        sys.exit(1)

    print(f"Building features from {args.input_csv} ...")
    df = build_feature_table(args.input_csv)

    dummies = pd.get_dummies(df["txn_type"], prefix="txn_type")
    df = pd.concat([df, dummies], axis=1)
    for c in components["feature_cols"]:
        if c not in df.columns:
            df[c] = 0

    scored = score_ensemble(df, components)

    flagged = scored[scored["flagged"] == 1].sort_values("fraud_probability", ascending=False)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    flagged.to_csv(args.out, index=False)

    n_blocked = int(scored["blocked"].sum())
    print(f"Scored {len(scored)} transactions. {len(flagged)} flagged "
          f"(threshold={config.ALERT_THRESHOLD}), {n_blocked} would be auto-blocked "
          f"(threshold={config.BLOCK_THRESHOLD}).")
    print(f"Flagged transactions written to {args.out}")


if __name__ == "__main__":
    main()
