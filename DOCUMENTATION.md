# System Documentation — Mobile Money Fraud Detection System

This is the technical reference for the system: architecture, data model,
detection/prevention pipeline, API, frontend, configuration, and how to
run it. For a fast getting-started path, see [README.md](README.md) — this
document goes deeper and is meant to stand on its own.

Note on scope: this document does **not** include the baseline-vs-XGBoost
model comparison (rule engine / logistic regression / random forest /
isolation forest / local outlier factor vs. XGBoost, evaluated on
PR-AUC/ROC-AUC/precision/recall). That comparison is reported in the
project's written monograph. `ml/train.py` still produces it
(`outputs/model_comparison.csv`) as part of the training run — it's simply
not surfaced through the API or dashboard.

## 1. Purpose

Mobile money fraud (account takeover, SIM-swap fraud, social-engineering
cash-outs, money-mule laundering) has to be caught in the seconds between
a transaction being initiated and it settling — not discovered in a
monthly reconciliation report. This system is a reference implementation
of that requirement end to end: ingest transactions, score them against a
trained model **and** an independent rule engine in near-real time,
surface anything suspicious to analysts, and automatically stop an
account that's clearly compromised from transacting further, rather than
just logging an alert for someone to read later.

It is built around a synthetic PaySim-style mobile money dataset (50
users, 2,000 seed transactions, a live traffic simulator) so it can be
demonstrated and evaluated without a production data-sharing agreement,
but every component — schema, feature pipeline, scoring loop, prevention
mechanism — is written the way it would need to work against a real
transaction feed.

## 2. Architecture

```
┌─────────────┐     ┌──────────────────────────────────────────┐
│  feeder.py   │────▶│              Postgres                     │
│ (simulates   │     │  users · devices · subscribers · locations │
│  live telco  │     │  transactions · user_profiles              │
│  traffic)    │     │  user_pair_history · fraud_alerts           │
└─────────────┘     └──────────────────────────────────────────┘
       ▲                        │            ▲
       │ excludes               │ reads      │ writes
       │ suspended              │ unscored   │ scores/alerts/
       │ accounts               ▼            │ blocks/suspensions
       │              ┌──────────────────────┴───┐
       │              │       monitor.py           │
       └──────────────│  ensemble scoring loop      │
                       │  (ml/ensemble.py)            │
                       └──────────────────────────────┘
                                    │
                       ┌────────────┴────────────┐
                       │  XGBoost · Isolation      │
                       │  Forest · Local Outlier   │
                       │  Factor · Rule Engine      │
                       │  (models/*.json, *.joblib) │
                       └────────────────────────────┘
                                    ▲
                                    │ trained once by
                              ml/train.py

┌──────────────┐        ┌───────────────┐        ┌─────────────────┐
│  api/main.py  │◀──────│   Postgres     │        │   frontend/       │
│  (FastAPI,    │ reads │  (same DB)     │        │  React dashboard   │
│   read-only)  │       │                │───────▶│  polls api/main.py │
└──────────────┘        └───────────────┘  (via   └─────────────────┘
                                              HTTP)
```

**Two scoring paths share one implementation.** `ml/train.py` (offline,
CSV-based) and `monitor/monitor.py` (live, database-based) both compute
features via the exact same code path
(`ml/online_features.py:compute_batch_features`), so there is no risk of
train/serve skew — a bug fixed in one is fixed in both, because there is
only one.

**The monitor never rescans transaction history.** After
`database/init_profiles.py` runs once, each user's behavioral state
(running mean/variance of spend, transaction count, distinct
counterparties) lives in `user_profiles` — one row per user, updated in
place with Welford's online algorithm. Scoring a new batch costs one
bounded query (`WHERE scored_at IS NULL`), one indexed primary-key lookup
per user touched by that batch, and one small indexed range query for
velocity features. None of that scales with total history size.

## 3. Data model

Full DDL: [database/schema.sql](database/schema.sql). Key tables:

| Table | Purpose |
|---|---|
| `users` | Identity, KYC status, denormalized location. `kyc_status = 'suspended'` is how prevention is enforced. |
| `devices` / `subscribers` / `subscriber_device_links` | IMEI/IMSI modeled separately and linked over time — SIM-swap and device-cloning are both visible as link changes, not lost by collapsing the two identifiers. |
| `user_locations` | Location ping history; a trigger keeps `users.current_*`/`avg_*` in sync. |
| `user_profiles` | Each user's running behavioral baseline (O(1) lookup/update, never a full rescan). |
| `user_pair_history` | Which sender→receiver pairs have transacted before (existence check for "new counterparty"). |
| `transactions` | One row per transaction, plus the scoring output columns: `fraud_probability`, `flagged`, `blocked`, `block_reason`, `model_version`, `scored_at`. |
| `fraud_alerts` | One row per flagged transaction; `alert_status` includes `'auto_blocked'` for ensemble-triggered blocks. |
| `v_alert_review_queue` (view) | Analyst-facing join of `fraud_alerts` + `transactions` + both users, including `blocked`/`block_reason`. |

## 4. The detection pipeline

### 4.1 Feature engineering

25 features per transaction, computed identically offline
(`ml/feature_engineering.py`, used by `ml/train.py` and
`database/init_profiles.py`) and online (`ml/online_features.py`, used by
`monitor.py`):

- **Transaction-level** (11): amount (raw + log), sender/receiver balance
  delta and reconciliation error, "account emptied" flag,
  "insufficient funds executed anyway" flag, cash-out/transfer flag,
  hour of day, night-transaction flag.
- **Behavioral/historical** (14): transaction count so far, running
  mean/std/max spend (Welford's algorithm), amount z-score vs. the
  sender's own history, time since last transaction, 1h/6h/24h velocity
  counts, distinct counterparties, "new counterparty" flag, receiver
  incoming count, receiver distinct senders, receiver fan-in ratio.

### 4.2 The four models

| Model | Type | Role |
|---|---|---|
| XGBoost | supervised | Primary learned model — patterns from confirmed fraud labels. |
| Isolation Forest | unsupervised | Flags globally rare/extreme feature combinations — useful before any fraud is confirmed, or for fraud patterns not in the training labels. |
| Local Outlier Factor | unsupervised | Flags *local* density outliers — a different anomaly shape than Isolation Forest's global partitioning, deliberately run alongside it rather than instead of it. |
| Rule engine | rule-based | Transparent, auditable threshold rules an ops team can read without a data science background. |

All four are trained/fitted by `ml/train.py` and persisted to `models/`:
`xgboost_model.json`, `isolation_forest.joblib`, `lof.joblib`,
`rule_engine.joblib` (plus `feature_list.json`, the exact column order
XGBoost expects).

### 4.3 Why XGBoost's training procedure matters

An earlier iteration of `train_xgboost` (`ml/train.py`) used `aucpr` as
the early-stopping metric. With only ~17 fraud examples in 2,000 rows,
`aucpr` saturates at its ceiling almost immediately — the model can rank
those few positives above everything else after a single tree, so early
stopping fired at `best_iteration == 0`. The result technically scored
PR-AUC/ROC-AUC of 1.0 (perfect ranking) but output only two
near-constant probabilities (~0.48 for every legitimate transaction,
~0.52 for every fraud one) — correct ranking, useless as a probability.

The fix: `eval_metric="logloss"` (which keeps improving well past the
point where ranking is "solved," because it scores confidence, not just
order) with a larger early-stopping patience (50 rounds), plus tighter
regularization for a dataset this small (`max_depth=4`,
`min_child_weight=5`, `reg_lambda=2.0`). Result: legitimate transactions
score ~0.3% on average (max 24%), fraud scores 82–93% — a real,
honestly-earned probability spread.

**This is also why the ensemble applies no artificial floor.** A prior
version forced `fraud_probability` to at least 0.80 whenever signals
"agreed," to compensate for the undertrained model above. That was
removed once the actual training bug was fixed — `fraud_probability` is
now exactly the weighted blend computed below, nothing added.

### 4.4 The rule engine (`ml/rules.py`)

Eight named rules, each contributing a weight to `rule_score` (summed,
capped at 1.0) when triggered:

| Rule | Weight | Severe? | Signal |
|---|---|---|---|
| `balance_mismatch` | 0.9 | ✅ | Sender/receiver post-transaction balance doesn't reconcile with the amount moved (beyond a learned, per-side tolerance — see §4.5). |
| `insufficient_funds_executed` | 0.9 | ✅ | A transaction executed for more than the sender's balance had. |
| `account_drained` | 0.7 | ✅ | Sender's balance hit zero on a transaction above the learned "large amount" cutoff. |
| `extreme_amount_vs_self` | 0.5 | — | Amount is a z-score outlier (>4σ) against the sender's own history. |
| `legacy_amount_cutoff` | 0.3 | — | Amount exceeds the 95th percentile of training amounts — the "flag anything large" rule most legacy systems run. |
| `velocity_burst` | 0.4 | — | Transaction count in the last hour exceeds a learned high-percentile cutoff. |
| `new_counterparty_large_night_cashout` | 0.4 | — | New counterparty + night hours + cash-out/transfer + large amount, together. |
| `mule_fanin_pattern` | 0.4 | — | Receiver has both a high incoming-transaction volume AND a high fraction of distinct new senders — a money-mule signature. |

**Only `severe` rules can trigger a block on their own.** This is a
deliberate design correction: an earlier version triggered a hard block
whenever *cumulative* `rule_score` crossed a threshold, which let two
individually-unremarkable medium-confidence rules (`legacy_amount_cutoff`
+ `extreme_amount_vs_self`) combine into a block neither justified alone
— verified to be the majority source of false blocks. The three `severe`
rules were each verified (on the shipped synthetic dataset) to have
**zero** false positives on their own while catching 100% of injected
fraud; medium-confidence rules still feed into `rule_score` (and so into
the blended probability) but cannot auto-block by themselves.

### 4.5 Calibration is learned, not hardcoded

Every rule cutoff except the self-relative z-score is a **percentile of
the training population**, fitted in `RuleEngine.fit()`:
`legacy_amount_cutoff` (95th percentile of amount), `large_amount_cutoff`
(99th), `balance_error_cutoff` (99th percentile of reconciliation error,
with a currency-unit floor), `fanin_ratio_cutoff` / `fanin_min_incoming`
(99.5th / 90th), `velocity_1h_cutoff` (99.5th, floored at 5). This is what
makes the engine portable: a rule engine hardcoded to one dataset's
currency scale and user count either never fires or fires on nearly
everything once pointed at a different one.

One data-quality subtlety worth documenting: this PaySim-style generator
leaves balance columns untouched (`sender_balance_delta == 0`) for many
rows regardless of transaction type — that's "balance wasn't tracked for
this row," not "no money moved." `balance_mismatch` and
`insufficient_funds_executed` are evaluated only on the side (sender or
receiver) whose balance actually changed; ignoring this distinction was
the original source of a ~25–30% false-positive rate on those two rules.

### 4.6 The ensemble (`ml/ensemble.py`)

```
fraud_probability = clip(
    0.55 × xgb_probability
  + 0.15 × isolation_forest_score   (calibrated against training-set range, see below)
  + 0.15 × local_outlier_factor_score
  + 0.15 × rule_score
, 0, 1)

flagged = fraud_probability >= ALERT_THRESHOLD        (0.5)
blocked = fraud_probability >= BLOCK_THRESHOLD (0.8)   OR any `severe` rule fired
```

Weights live in `config.ENSEMBLE_WEIGHTS`. The two unsupervised models'
raw `decision_function` output is wrapped in `CalibratedUnsupervised`,
which min-max-normalizes against bounds captured from the **training
set's own score range** at persist time — not per-batch. Per-batch
min-max would be meaningless for `monitor.py`'s small live batches (with
a batch of 1, min == max and every score would collapse to 0); a fixed
reference range keeps scores stable and comparable regardless of how many
transactions are in a given poll cycle.

## 5. Prevention

Detection alone — an alert a human reviews hours later — doesn't stop a
draining account from making a second, third, or tenth transaction in the
meantime. Prevention closes that gap:

1. `monitor.py` scores a batch and calls `write_alerts_to_db.write_alerts`,
   which sets `transactions.blocked` / `block_reason` and inserts a
   `fraud_alerts` row with `alert_status = 'auto_blocked'` for anything
   blocked (vs. `'open'` for a flag that didn't cross the block bar).
2. It then calls `write_alerts_to_db.suspend_users` on every sender
   behind a blocked transaction, which flips `users.kyc_status` to
   `'suspended'` — idempotent, only touches accounts not already
   suspended.
3. `feeder/feeder.py` re-fetches the suspended set before every batch and
   excludes those accounts from originating new transactions — the
   account genuinely stops being able to transact, not just gets flagged
   after the fact. (Receiving is still allowed — investigation holds
   don't need to bounce incoming refunds.)

In production, step 3's equivalent is whatever system authorizes a
transaction before it commits — this feeder stands in for that system,
so the same suspended-account check belongs at that authorization point.

## 6. Live components

### 6.1 `monitor/monitor.py` — the scoring loop

Polls `transactions WHERE scored_at IS NULL`, looks up just the
sender/receiver profiles and recent velocity history touched by that
batch, scores with the ensemble, writes results back, suspends accounts
behind any block, and updates the touched profile rows. `--once` runs a
single cycle; `--cycles N` stops after N; otherwise it polls forever at
`config.MONITOR_POLL_INTERVAL_SECONDS`.

### 6.2 `feeder/feeder.py` — traffic simulator

Generates plausible transactions between real users in the database,
occasionally injecting a deliberately fraud-like transaction (a sudden
large transfer/cash-out that drains the account) so detection can be
observed directly. `is_fraud` on injected rows is ground truth for
demonstration only — a real feed wouldn't know this at ingestion time.

### 6.3 `api/main.py` — read-only JSON layer

A thin FastAPI app in front of Postgres for the dashboard to poll. No
business logic — every endpoint is a direct read of tables/views the
pipeline above already maintains.

| Endpoint | Returns |
|---|---|
| `GET /api/health` | Liveness + DB connectivity check. |
| `GET /api/stats` | One summary row: transaction/flag/block/alert/suspension counts, average fraud probability, current thresholds. |
| `GET /api/alerts?limit=&status=` | Recent rows from `v_alert_review_queue`, newest first. |
| `GET /api/transactions/recent?limit=` | Most recently *scored* transactions (not just flagged ones) — throughput visibility. |
| `GET /api/suspended` | Currently suspended accounts + how many blocked transactions triggered each one. |

CORS is wide open (`allow_origins: ["*"]`) by default — this is meant for
local/internal use; tighten it before exposing the API beyond your own
network.

### 6.4 `frontend/` — the live dashboard

A React (Vite) single-page app that polls the API every 4 seconds (stat
tiles, alert queue, live scoring feed, suspended accounts). No build
step is required to view it during development — `npm run dev` serves it
directly.

| Component | Shows |
|---|---|
| Stat tiles | Total/pending/flagged/blocked transaction counts, suspended accounts, open alerts. |
| Fraud alert queue | `v_alert_review_queue`, with a color-coded probability pill (never color alone — always paired with the numeric % and a text label) and the rule engine's fired reasons. |
| Live scoring feed | Most recently scored transactions, flagged or not — shows the monitor's throughput. |
| Suspended accounts | Who prevention has frozen, when, and how many blocked transactions triggered it. |

Design notes: the categorical/status color palette is validated against
WCAG contrast and colorblind-safety checks (see
`frontend/src/index.css`'s CSS custom properties); dark mode is a real
second token set via `prefers-color-scheme`, not a filter.

## 7. Configuration reference

Everything lives in [config.py](config.py) — the single source of truth
every module reads from. The most consequential knobs:

| Setting | Default | Effect |
|---|---|---|
| `ALERT_THRESHOLD` | 0.5 | `fraud_probability` at/above this → `flagged`. |
| `BLOCK_THRESHOLD` | 0.8 | `fraud_probability` at/above this (or any `severe` rule) → `blocked` + account suspended. |
| `ENSEMBLE_WEIGHTS` | xgb 0.55 / iso 0.15 / lof 0.15 / rules 0.15 | How the four signals are blended into `fraud_probability`. |
| `RULE_*_PERCENTILE` | see §4.5 | Where each rule's learned cutoff sits in the training distribution. |
| `VELOCITY_WINDOWS_HOURS` | [1, 6, 24] | Lookback windows for velocity features. |
| `AUTO_SCALE_POS_WEIGHT` | True | Whether XGBoost's `scale_pos_weight` is auto-derived from the training class imbalance. |
| `TEST_SIZE` | 0.2 | Fraction of data (by time, not randomly) held out for evaluation. |
| `MONITOR_POLL_INTERVAL_SECONDS` | 10.0 | How often `monitor.py` checks for new transactions. |
| `FEEDER_FRAUD_INJECTION_RATE` | 0.05 | Fraction of feeder-generated transactions that are deliberately fraud-like. |

## 8. Running the system

See [README.md](README.md) sections 1–5 for the full step-by-step
(database → train → live loop → dashboard). Short version:

```bash
docker compose up -d
python database/build_database.py --transactions data/synthetic.csv --fresh
python ml/train.py data/synthetic.csv
python database/init_profiles.py

python feeder/feeder.py --batch-size 10 --interval 5      # terminal 1
python monitor/monitor.py --interval 10                    # terminal 2
uvicorn api.main:app --reload --port 8000                   # terminal 3
cd frontend && npm run dev                                   # terminal 4
```

Dashboard: http://localhost:5173. Analyst SQL access:
`v_alert_review_queue` (see README for example queries).

## 9. Known limitations

- **Synthetic data.** The shipped dataset (2,000 transactions, 50 users,
  17 fraud) is enough to demonstrate the pipeline and validate that
  detection/prevention work correctly, but not to make statistical claims
  about real-world precision/recall at scale — model comparison and
  statistical evaluation belong in the monograph, using whatever dataset
  that analysis is run against.
- **Percentile-learned rule cutoffs assume the training population is
  representative.** If deployed against a materially different
  transaction mix without retraining, cutoffs should be refreshed (rerun
  `ml/train.py`).
- **Prevention only covers this feeder's simulated authorization path.**
  In production, the equivalent suspended-account check belongs in the
  actual transaction-authorization system, not this demo feeder.
- **CORS is wide open by default** in `api/main.py` — appropriate for
  local demonstration, not for exposing the API beyond a trusted network
  without tightening `allow_origins`.
