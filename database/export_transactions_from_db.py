"""
export_transactions_from_db.py
-------------------------------
DB -> CSV, in the exact column layout ml/ expects (config.COLS - the same
PaySim-style names as data/synthetic.csv). BASE_QUERY is also reused
directly by database/init_profiles.py (full history, empty where_clause)
and monitor/monitor.py (WHERE scored_at IS NULL) so all three paths read
transactions in exactly the same shape.

Usage:
    python database/export_transactions_from_db.py --out data/from_db.csv
"""

import _pathfix  # noqa: F401
import os
import sys
import argparse
import pandas as pd

import config

BASE_QUERY = """
    SELECT
        txn_id,
        txn_step              AS step,
        txn_type               AS type,
        amount,
        sender_user_id          AS "nameOrig",
        sender_balance_old       AS "oldbalanceOrg",
        sender_balance_new        AS "newbalanceOrig",
        receiver_user_id           AS "nameDest",
        receiver_balance_old        AS "oldbalanceDest",
        receiver_balance_new         AS "newbalanceDest",
        is_fraud                      AS "isFraud",
        sender_imei, receiver_imei
    FROM transactions
    {where_clause}
    ORDER BY txn_step, txn_id
"""


def main():
    try:
        import psycopg2
    except ImportError:
        print("psycopg2 is not installed. Install it with:\n    pip install psycopg2-binary")
        sys.exit(1)

    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", default=config.DB_DSN)
    parser.add_argument("--out", default=os.path.join(config.BASE_DIR, "data", "from_db.csv"))
    args = parser.parse_args()

    conn = psycopg2.connect(args.dsn)
    try:
        df = pd.read_sql(BASE_QUERY.format(where_clause=""), conn)
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        df.to_csv(args.out, index=False)
        print(f"Exported {len(df)} transactions to {args.out}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
