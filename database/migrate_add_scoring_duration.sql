-- =============================================================================
-- migrate_add_scoring_duration.sql - adds transactions.scoring_duration_ms
-- to an EXISTING database: real engine processing time per transaction
-- (ml/ensemble.py:score_ensemble), used by /api/stats' scoring-latency
-- figures instead of the misleading scored_at - created_at gap (which
-- just measures how long a transaction sat waiting for someone to run
-- monitor.py). Safe to re-run.
--
-- Usage:
--   psql "$MOMO_FRAUD_DSN" -f database/migrate_add_scoring_duration.sql
-- =============================================================================

BEGIN;

ALTER TABLE transactions ADD COLUMN IF NOT EXISTS scoring_duration_ms DOUBLE PRECISION;

COMMIT;
