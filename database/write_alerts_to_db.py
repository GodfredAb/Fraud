"""
write_alerts_to_db.py
----------------------
Model output -> DB. Given a scored batch (txn_id, fraud_probability,
flagged, blocked, block_reason - see ml/ensemble.py), writes the score
back onto the transactions row (so it's marked as scored - scored_at IS
NULL is what makes a transaction "pending" for monitor/monitor.py) and
inserts a fraud_alerts row for anything flagged, so analysts can work the
queue via v_alert_review_queue.

suspend_users is the other half of PREVENTION (not just detection): once
the ensemble/rule engine hard-blocks a transaction, the sender's account
is frozen (kyc_status -> 'suspended') so it stops being eligible to send
further transactions - see feeder/feeder.py, which excludes suspended
senders from the traffic it generates, closing the loop end to end.
"""

import datetime as dt


def write_alerts(conn, scored_df, model_version: str):
    """scored_df: DataFrame with columns txn_id, fraud_probability, flagged,
    blocked, block_reason, scoring_duration_ms (one row per transaction
    just scored, any order). Returns (n_transactions_updated, n_alerts_inserted)."""
    from psycopg2.extras import execute_values

    if scored_df.empty:
        return 0, 0

    now = dt.datetime.now()
    update_rows = [
        (int(r.txn_id), float(r.fraud_probability), bool(r.flagged),
         bool(r.blocked), (r.block_reason or None), model_version, now,
         float(r.scoring_duration_ms))
        for r in scored_df.itertuples()
    ]

    with conn.cursor() as cur:
        execute_values(cur, """
            UPDATE transactions AS t SET
                fraud_probability = v.fraud_probability,
                flagged            = v.flagged,
                blocked             = v.blocked,
                block_reason         = v.block_reason,
                model_version         = v.model_version,
                scored_at              = v.scored_at,
                scoring_duration_ms     = v.scoring_duration_ms
            FROM (VALUES %s) AS v(txn_id, fraud_probability, flagged, blocked, block_reason, model_version, scored_at, scoring_duration_ms)
            WHERE t.txn_id = v.txn_id
        """, update_rows,
            template="(%s::bigint, %s::numeric, %s::boolean, %s::boolean, %s::varchar, %s::varchar, %s::timestamp, %s::double precision)")
        # Note: NOT cur.rowcount here - execute_values pages large batches
        # into multiple UPDATE statements (default page_size=100), and
        # rowcount only reflects the last page executed, not the total.
        # Every txn_id in update_rows came straight from the transactions
        # table, so every one of them is guaranteed to match and update.
        n_updated = len(update_rows)

        alert_rows = [
            (int(r.txn_id), float(r.fraud_probability), model_version,
             "auto_blocked" if r.blocked else "open")
            for r in scored_df.itertuples() if r.flagged
        ]
        n_alerts = 0
        if alert_rows:
            execute_values(cur, """
                INSERT INTO fraud_alerts (txn_id, fraud_probability, model_version, alert_status)
                VALUES %s
            """, alert_rows)
            n_alerts = len(alert_rows)

    conn.commit()
    return n_updated, n_alerts


def suspend_users(conn, user_ids):
    """Prevention: freeze an account (kyc_status -> 'suspended') once one
    of its transactions has been auto-blocked, so no further transactions
    from it should be authorized until a human reviews it. Idempotent -
    only touches accounts not already suspended. Returns the number of
    accounts newly suspended."""
    if not user_ids:
        return 0
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE users SET kyc_status = 'suspended', updated_at = now()
            WHERE user_id = ANY(%s) AND kyc_status != 'suspended'
        """, (list(set(user_ids)),))
        n = cur.rowcount
    conn.commit()
    return n
