-- =============================================================================
-- schema.sql - Group 13 Mobile Money: Users, Devices, Subscribers, Transactions
-- =============================================================================
-- Design notes:
--   * "Device" (IMEI) and "Subscriber identity" (IMSI/SIM) are modeled as
--     SEPARATE entities linked by subscriber_device_links. This matches how
--     telcos actually see the world: a person can swap SIMs into the same
--     phone, or move their SIM into a new phone - and BOTH of those events
--     are classic fraud signals (SIM-swap fraud, device-cloning fraud).
--     Collapsing IMEI+IMSI into one column would throw that signal away.
--   * users.avg_latitude/avg_longitude are denormalized (kept in sync via
--     trigger) so fraud-scoring queries don't need to aggregate
--     user_locations on every lookup - current location changes constantly,
--     average location is what "normal" looks like for that user.
--   * transactions stores sender_imei/receiver_imei directly (as requested)
--     in addition to sender_user_id/receiver_user_id, so you can query
--     "which transactions came from this exact handset" independent of who
--     is currently paired with it.
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- USERS: basic identity info
-- ---------------------------------------------------------------------------
CREATE TABLE users (
    user_id             VARCHAR(20)   PRIMARY KEY,        -- e.g. 'C12' (matches source data); use UUID in production
    full_name           VARCHAR(120)  NOT NULL,
    national_id         VARCHAR(50)   UNIQUE,              -- Ghana Card / national ID number
    date_of_birth        DATE,
    gender              VARCHAR(10),
    msisdn              VARCHAR(20)   UNIQUE NOT NULL,      -- primary phone number
    kyc_status          VARCHAR(20)   NOT NULL DEFAULT 'verified'
                         CHECK (kyc_status IN ('pending','verified','rejected','suspended')),
    registration_date   TIMESTAMP     NOT NULL DEFAULT now(),

    -- Denormalized location snapshot (kept current via trigger from user_locations)
    current_latitude    NUMERIC(9,6),
    current_longitude   NUMERIC(9,6),
    current_location_at TIMESTAMP,
    avg_latitude         NUMERIC(9,6),
    avg_longitude         NUMERIC(9,6),

    created_at           TIMESTAMP     NOT NULL DEFAULT now(),
    updated_at           TIMESTAMP     NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- DEVICES: physical handsets, identified by IMEI
-- ---------------------------------------------------------------------------
CREATE TABLE devices (
    device_id       SERIAL        PRIMARY KEY,
    imei            VARCHAR(20)   UNIQUE NOT NULL,
    manufacturer    VARCHAR(50),
    model           VARCHAR(80),
    first_seen_at   TIMESTAMP     NOT NULL DEFAULT now(),
    is_blacklisted  BOOLEAN       NOT NULL DEFAULT FALSE   -- e.g. reported stolen
);

-- ---------------------------------------------------------------------------
-- SUBSCRIBERS: SIM / subscriber identity (IMSI), owned by a user
-- ---------------------------------------------------------------------------
CREATE TABLE subscribers (
    subscriber_id   SERIAL        PRIMARY KEY,
    imsi            VARCHAR(20)   UNIQUE NOT NULL,
    msisdn          VARCHAR(20)   NOT NULL,
    user_id         VARCHAR(20)   NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    activated_at    TIMESTAMP     NOT NULL DEFAULT now(),
    is_active       BOOLEAN       NOT NULL DEFAULT TRUE
);
CREATE INDEX idx_subscribers_user ON subscribers(user_id);

-- ---------------------------------------------------------------------------
-- SUBSCRIBER_DEVICE_LINKS: ties IMEI <-> IMSI over time (many-to-many)
-- A new row / is_current flip here on an existing subscriber = SIM swapped
-- into a new phone. A new subscriber pairing with an existing device = a
-- new SIM used in a known handset. Both are fraud-relevant events.
-- ---------------------------------------------------------------------------
CREATE TABLE subscriber_device_links (
    link_id           SERIAL      PRIMARY KEY,
    subscriber_id     INT         NOT NULL REFERENCES subscribers(subscriber_id) ON DELETE CASCADE,
    device_id         INT         NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
    first_paired_at   TIMESTAMP   NOT NULL DEFAULT now(),
    last_seen_at      TIMESTAMP   NOT NULL DEFAULT now(),
    is_current        BOOLEAN     NOT NULL DEFAULT TRUE,
    UNIQUE (subscriber_id, device_id)
);
CREATE INDEX idx_sdl_subscriber ON subscriber_device_links(subscriber_id);
CREATE INDEX idx_sdl_device ON subscriber_device_links(device_id);

-- ---------------------------------------------------------------------------
-- USER_LOCATIONS: location ping history (used to derive current + average)
-- ---------------------------------------------------------------------------
CREATE TABLE user_locations (
    location_id   BIGSERIAL     PRIMARY KEY,
    user_id       VARCHAR(20)   NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    latitude      NUMERIC(9,6)  NOT NULL,
    longitude     NUMERIC(9,6)  NOT NULL,
    recorded_at   TIMESTAMP     NOT NULL DEFAULT now(),
    source        VARCHAR(30)   NOT NULL DEFAULT 'cell_tower'
                  CHECK (source IN ('gps','cell_tower','wifi','agent_registration'))
);
CREATE INDEX idx_user_locations_user_time ON user_locations(user_id, recorded_at DESC);

-- Keep users.current_* and users.avg_* in sync whenever a new location lands
CREATE OR REPLACE FUNCTION fn_update_user_location_summary()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE users
    SET current_latitude    = NEW.latitude,
        current_longitude   = NEW.longitude,
        current_location_at = NEW.recorded_at,
        avg_latitude          = (SELECT AVG(latitude)  FROM user_locations WHERE user_id = NEW.user_id),
        avg_longitude          = (SELECT AVG(longitude) FROM user_locations WHERE user_id = NEW.user_id),
        updated_at           = now()
    WHERE user_id = NEW.user_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_update_user_location_summary
AFTER INSERT ON user_locations
FOR EACH ROW EXECUTE FUNCTION fn_update_user_location_summary();

-- ---------------------------------------------------------------------------
-- USER_PROFILES: running behavioral state per user, maintained incrementally.
-- This is what lets the monitor score NEW transactions without ever
-- rescanning the full transaction history: after the model "studies" all
-- historical data once (database/init_profiles.py), the final cumulative
-- state for each user is stored here. Every new transaction updates just
-- its sender's and receiver's rows - an O(1) lookup/update, not a table scan.
-- ---------------------------------------------------------------------------
CREATE TABLE user_profiles (
    user_id                     VARCHAR(20)  PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,

    -- Sender-side running stats (Welford's online algorithm for mean/variance,
    -- so we never need to re-read past amounts to update mean/std).
    -- NOTE: sender_last_txn_step uses the same "step"/hour-counter unit as
    -- ml/feature_engineering.py's timestamp feature (config.TIMESTAMP_IS_DATETIME
    -- = False by default) - NOT a wall-clock timestamp. Keeping this consistent
    -- with training is what makes velocity/recency features line up correctly
    -- between training and live scoring.
    sender_txn_count            BIGINT            NOT NULL DEFAULT 0,
    sender_amount_mean          DOUBLE PRECISION  NOT NULL DEFAULT 0,
    sender_amount_m2            DOUBLE PRECISION  NOT NULL DEFAULT 0,  -- sum of squared diffs from mean
    sender_amount_max           DOUBLE PRECISION,
    sender_last_txn_step        DOUBLE PRECISION,
    sender_distinct_receivers   BIGINT            NOT NULL DEFAULT 0,

    -- Receiver-side running stats
    receiver_incoming_count     BIGINT            NOT NULL DEFAULT 0,
    receiver_distinct_senders   BIGINT            NOT NULL DEFAULT 0,

    updated_at                  TIMESTAMP         NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- USER_PAIR_HISTORY: which sender->receiver pairs have ever transacted.
-- Existence check for "is_new_counterparty" without scanning transactions.
-- ---------------------------------------------------------------------------
CREATE TABLE user_pair_history (
    sender_id     VARCHAR(20)  NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    receiver_id   VARCHAR(20)  NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    first_seen_at TIMESTAMP    NOT NULL DEFAULT now(),
    PRIMARY KEY (sender_id, receiver_id)
);


CREATE TABLE transactions (
    txn_id                BIGSERIAL     PRIMARY KEY,
    txn_step              INT,                        -- raw 'step' from source data
    txn_timestamp         TIMESTAMP,
    txn_type              VARCHAR(20)   NOT NULL,      -- CASH_IN, CASH_OUT, PAYMENT, TRANSFER, DEBIT

    amount                NUMERIC(14,2) NOT NULL,

    sender_user_id        VARCHAR(20)   REFERENCES users(user_id),
    sender_imei           VARCHAR(20)   REFERENCES devices(imei),
    sender_balance_old    NUMERIC(14,2),
    sender_balance_new    NUMERIC(14,2),

    receiver_user_id      VARCHAR(20)   REFERENCES users(user_id),
    receiver_imei         VARCHAR(20)   REFERENCES devices(imei),
    receiver_balance_old  NUMERIC(14,2),
    receiver_balance_new  NUMERIC(14,2),

    -- Ground-truth label (if known) + model outputs (filled in by score.py)
    is_fraud              BOOLEAN       DEFAULT FALSE,
    fraud_probability     NUMERIC(6,5),
    flagged               BOOLEAN       DEFAULT FALSE,
    -- Prevention (not just detection): set by the ensemble/rule engine
    -- (ml/ensemble.py) when fraud_probability crosses config.BLOCK_THRESHOLD
    -- or a hard rule fires - see database/write_alerts_to_db.py:suspend_users,
    -- which also freezes the sender's account when this is set.
    blocked                BOOLEAN       NOT NULL DEFAULT FALSE,
    block_reason           VARCHAR(300),
    model_version         VARCHAR(50),
    scored_at             TIMESTAMP,

    created_at            TIMESTAMP     NOT NULL DEFAULT now()
);
CREATE INDEX idx_txn_sender      ON transactions(sender_user_id);
CREATE INDEX idx_txn_receiver    ON transactions(receiver_user_id);
CREATE INDEX idx_txn_sender_imei ON transactions(sender_imei);
CREATE INDEX idx_txn_recv_imei   ON transactions(receiver_imei);
CREATE INDEX idx_txn_timestamp   ON transactions(txn_timestamp);
CREATE INDEX idx_txn_flagged     ON transactions(flagged) WHERE flagged = TRUE;
CREATE INDEX idx_txn_blocked     ON transactions(blocked) WHERE blocked = TRUE;
CREATE INDEX idx_txn_unscored    ON transactions(scored_at) WHERE scored_at IS NULL;
-- Composite index so "recent transactions for these senders" is a fast
-- bounded range scan, never a full-table scan, no matter how much history
-- accumulates. Indexed on txn_step (the unit feature engineering actually
-- uses for time), not txn_timestamp.
CREATE INDEX idx_txn_sender_step ON transactions(sender_user_id, txn_step);

-- ---------------------------------------------------------------------------
-- FRAUD_ALERTS: analyst-facing alert queue, one row per flagged transaction
-- (this is what src/score.py from the modeling pipeline writes into)
-- ---------------------------------------------------------------------------
CREATE TABLE fraud_alerts (
    alert_id           BIGSERIAL   PRIMARY KEY,
    txn_id             BIGINT      NOT NULL REFERENCES transactions(txn_id) ON DELETE CASCADE,
    fraud_probability  NUMERIC(6,5) NOT NULL,
    model_version       VARCHAR(50),
    alert_status        VARCHAR(20) NOT NULL DEFAULT 'open'
                        CHECK (alert_status IN ('open','under_review','confirmed_fraud','false_positive','auto_blocked')),
    reviewed_by          VARCHAR(100),
    reviewed_at          TIMESTAMP,
    created_at           TIMESTAMP   NOT NULL DEFAULT now()
);
CREATE INDEX idx_alerts_status ON fraud_alerts(alert_status);
CREATE INDEX idx_alerts_txn ON fraud_alerts(txn_id);

-- ---------------------------------------------------------------------------
-- Convenience view: everything a fraud analyst needs for one alert, joined
-- ---------------------------------------------------------------------------
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
