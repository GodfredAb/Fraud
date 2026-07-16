-- =============================================================================
-- migrate_add_blocking.sql - adds rule-based prevention (blocking) to an
-- EXISTING database that was built before this feature landed, without
-- dropping any data (unlike `build_database.py --fresh`, which rebuilds
-- everything from scratch). Safe to re-run.
--
-- Usage:
--   psql "$MOMO_FRAUD_DSN" -f database/migrate_add_blocking.sql
-- =============================================================================

BEGIN;

ALTER TABLE transactions ADD COLUMN IF NOT EXISTS blocked BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS block_reason VARCHAR(300);
CREATE INDEX IF NOT EXISTS idx_txn_blocked ON transactions(blocked) WHERE blocked = TRUE;

ALTER TABLE fraud_alerts DROP CONSTRAINT IF EXISTS fraud_alerts_alert_status_check;
ALTER TABLE fraud_alerts ADD CONSTRAINT fraud_alerts_alert_status_check
    CHECK (alert_status IN ('open','under_review','confirmed_fraud','false_positive','auto_blocked'));

CREATE OR REPLACE VIEW v_alert_review_queue AS
SELECT
    a.alert_id,
    a.alert_status,
    a.fraud_probability,
    t.txn_id, t.txn_timestamp, t.txn_type, t.amount,
    t.blocked, t.block_reason,
    su.user_id  AS sender_user_id,  su.full_name AS sender_name,  su.msisdn AS sender_msisdn,
    t.sender_imei,
    su.current_latitude AS sender_current_lat, su.current_longitude AS sender_current_lon,
    su.avg_latitude AS sender_avg_lat, su.avg_longitude AS sender_avg_lon,
    ru.user_id  AS receiver_user_id, ru.full_name AS receiver_name, ru.msisdn AS receiver_msisdn,
    t.receiver_imei,
    a.created_at AS alert_created_at
FROM fraud_alerts a
JOIN transactions t ON t.txn_id = a.txn_id
LEFT JOIN users su ON su.user_id = t.sender_user_id
LEFT JOIN users ru ON ru.user_id = t.receiver_user_id;

COMMIT;
