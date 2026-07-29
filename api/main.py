"""
main.py (api/)
---------------
Small read-only JSON API in front of the Postgres database, for the React
dashboard (frontend/) to poll. Deliberately thin: every endpoint is a
straight read of tables/views monitor.py and write_alerts_to_db.py already
maintain (transactions, fraud_alerts, users, v_alert_review_queue) - no
new business logic lives here, this just shapes existing state as JSON.

Note: this deliberately does NOT expose ml/train.py's baseline-vs-XGBoost
model comparison report (outputs/model_comparison.csv) - that belongs in
the project's written monograph, not the live operational dashboard.

Usage:
    pip install -r api/requirements.txt
    uvicorn api.main:app --reload --port 8000
"""

import os
import sys
import math
import datetime as dt

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import config

try:
    import psycopg2
    import psycopg2.extras
except ImportError as e:
    print(f"Missing dependency: {e}. Install with:\n    pip install -r api/requirements.txt")
    sys.exit(1)

app = FastAPI(title="Mobile Money Fraud Detection API")

# The React dev server runs on a different origin (5173) than this API
# (8000) - CORS has to be explicit for the browser to allow the fetches.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def get_conn():
    return psycopg2.connect(config.DB_DSN, cursor_factory=psycopg2.extras.RealDictCursor)


def query(sql: str, params: tuple = ()):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


@app.get("/api/health")
def health():
    try:
        query("SELECT 1")
        return {"status": "ok", "time": dt.datetime.now().isoformat()}
    except Exception as e:
        print(f"[health check] DB connection failed: {e!r}", flush=True)
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/api/stats")
def stats():
    """One summary row: everything the dashboard's stat tiles need in a
    single round trip."""
    row = query("""
        SELECT
            (SELECT count(*) FROM transactions)                                  AS total_transactions,
            (SELECT count(*) FROM transactions WHERE scored_at IS NOT NULL)      AS scored_transactions,
            (SELECT count(*) FROM transactions WHERE scored_at IS NULL)          AS pending_transactions,
            (SELECT count(*) FROM transactions WHERE flagged)                    AS flagged_transactions,
            (SELECT count(*) FROM transactions WHERE blocked)                    AS blocked_transactions,
            (SELECT count(*) FROM fraud_alerts WHERE alert_status = 'open')      AS open_alerts,
            (SELECT count(*) FROM users WHERE kyc_status = 'suspended')          AS suspended_accounts,
            (SELECT count(*) FROM users)                                        AS total_accounts,
            (SELECT max(scored_at) FROM transactions)                           AS last_scored_at,
            (SELECT avg(fraud_probability) FROM transactions WHERE scored_at IS NOT NULL) AS avg_fraud_probability
    """)[0]
    row["alert_threshold"] = config.ALERT_THRESHOLD
    row["block_threshold"] = config.BLOCK_THRESHOLD
    return row


@app.get("/api/alerts")
def alerts(limit: int = Query(25, ge=1, le=200), status: str | None = None):
    """Recent rows from v_alert_review_queue - the same view the SQL
    snippets in README.md point analysts at - newest first."""
    if status:
        return query(
            "SELECT * FROM v_alert_review_queue WHERE alert_status = %s "
            "ORDER BY alert_created_at DESC LIMIT %s",
            (status, limit),
        )
    return query("SELECT * FROM v_alert_review_queue ORDER BY alert_created_at DESC LIMIT %s", (limit,))


@app.get("/api/transactions/recent")
def recent_transactions(limit: int = Query(25, ge=1, le=200)):
    """The live feed: most recently SCORED transactions (not just flagged
    ones), so the dashboard shows monitor.py's throughput, not only the
    fraud cases."""
    return query("""
        SELECT txn_id, txn_timestamp, txn_type, amount,
               sender_user_id, receiver_user_id,
               fraud_probability, flagged, blocked, block_reason, scored_at
        FROM transactions
        WHERE scored_at IS NOT NULL
        ORDER BY scored_at DESC
        LIMIT %s
    """, (limit,))


@app.get("/api/transactions/{txn_id}")
def transaction_detail(txn_id: int):
    """Full detail for one transaction, for the dashboard's row-click
    drill-down - everything recent_transactions/alerts trims out (balances,
    device IMEIs, sender/receiver names) plus flagged/blocked reason and
    scored_at (the same instant flagged/blocked were set - see
    ml/ensemble.py:score_ensemble, which computes them together)."""
    rows = query("""
        SELECT
            t.txn_id, t.txn_step, t.txn_timestamp, t.txn_type, t.amount,
            t.sender_user_id, su.full_name AS sender_name, su.msisdn AS sender_msisdn,
            t.sender_imei, t.sender_balance_old, t.sender_balance_new,
            t.receiver_user_id, ru.full_name AS receiver_name, ru.msisdn AS receiver_msisdn,
            t.receiver_imei, t.receiver_balance_old, t.receiver_balance_new,
            t.is_fraud, t.fraud_probability, t.flagged, t.blocked, t.block_reason,
            t.model_version, t.scored_at, t.created_at
        FROM transactions t
        LEFT JOIN users su ON su.user_id = t.sender_user_id
        LEFT JOIN users ru ON ru.user_id = t.receiver_user_id
        WHERE t.txn_id = %s
    """, (txn_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="transaction not found")
    return rows[0]


def _haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance between two lat/lon points, in km."""
    if None in (lat1, lon1, lat2, lon2):
        return None
    r = 6371.0
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dp = math.radians(float(lat2) - float(lat1))
    dl = math.radians(float(lon2) - float(lon1))
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(r * 2 * math.asin(math.sqrt(a)), 1)


@app.get("/api/fraud-locations")
def fraud_locations(limit: int = Query(20, ge=1, le=100)):
    """Current vs. home location for the subscribers most likely to be
    committing fraud right now (highest fraud_probability on a flagged
    transaction they SENT), one row per subscriber - not per alert, unlike
    /api/alerts. users.current_*/avg_* are denormalized onto the user row
    by a DB trigger (see schema.sql) from user_locations ping history, so
    this is a single indexed lookup, not an aggregation over raw pings.
    distance_km is how far their current position is from where they
    normally are - a subscriber transacting from 40km away from their own
    home range is a meaningfully different risk picture than one two
    blocks from home, on top of whatever the transaction itself scored."""
    rows = query("""
        SELECT u.user_id, u.full_name, u.msisdn, u.kyc_status,
               u.current_latitude, u.current_longitude, u.current_location_at,
               u.avg_latitude, u.avg_longitude,
               f.max_fraud_probability, f.last_flagged_at, f.flagged_count
        FROM users u
        JOIN (
            SELECT sender_user_id,
                   MAX(fraud_probability) AS max_fraud_probability,
                   MAX(scored_at) AS last_flagged_at,
                   COUNT(*) AS flagged_count
            FROM transactions
            WHERE flagged = TRUE
            GROUP BY sender_user_id
        ) f ON f.sender_user_id = u.user_id
        ORDER BY f.max_fraud_probability DESC
        LIMIT %s
    """, (limit,))
    for r in rows:
        r["distance_from_home_km"] = _haversine_km(
            r["current_latitude"], r["current_longitude"], r["avg_latitude"], r["avg_longitude"]
        )
    return rows


@app.get("/api/suspended")
def suspended_accounts():
    """Accounts monitor.py has frozen via write_alerts_to_db.suspend_users,
    plus how many blocked transactions triggered each one."""
    return query("""
        SELECT u.user_id, u.full_name, u.msisdn, u.updated_at,
               count(t.txn_id) FILTER (WHERE t.blocked) AS blocked_txn_count
        FROM users u
        LEFT JOIN transactions t ON t.sender_user_id = u.user_id
        WHERE u.kyc_status = 'suspended'
        GROUP BY u.user_id, u.full_name, u.msisdn, u.updated_at
        ORDER BY u.updated_at DESC
    """)
