-- =============================================================================
-- migrate_widen_block_reason.sql - widens transactions.block_reason from
-- VARCHAR(300) to TEXT, and applies to any EXISTING database. ml/ensemble.py
-- now writes a full human-readable explanation (rule phrasing + behavioral
-- context vs the sender's own history) for every FLAGGED-or-blocked
-- transaction, not just a short machine slug for blocked ones - that no
-- longer reliably fits in 300 chars. Safe to re-run.
--
-- Usage:
--   psql "$MOMO_FRAUD_DSN" -f database/migrate_widen_block_reason.sql
-- =============================================================================

BEGIN;

-- v_alert_review_queue depends on this column, so it must be dropped and
-- recreated around the ALTER.
DROP VIEW IF EXISTS v_alert_review_queue;

ALTER TABLE transactions ALTER COLUMN block_reason TYPE TEXT;

CREATE VIEW v_alert_review_queue AS
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
