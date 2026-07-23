-- =============================================================================
-- migrate_add_device_change_tracking.sql - adds SIM-swap/device-cloning
-- detection to an EXISTING database: two columns on user_profiles tracking
-- each sender's last-seen IMEI and when their device last changed. Safe to
-- re-run.
--
-- Usage:
--   psql "$MOMO_FRAUD_DSN" -f database/migrate_add_device_change_tracking.sql
-- =============================================================================

BEGIN;

ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS sender_last_imei VARCHAR(20);
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS sender_last_device_change_step DOUBLE PRECISION;

COMMIT;
