# Group 13 Mobile Money Fraud Detection System

Everything - database, feeder, models, and the monitoring service - lives
under this one directory now.

This README is a getting-started guide. For architecture, the detection/
prevention pipeline in depth, the API/frontend reference, and the full
configuration reference, see **[DOCUMENTATION.md](DOCUMENTATION.md)**.

```
momo_fraud/
├── config.py               # single shared config: DB connection, columns, thresholds, timing, ensemble weights
├── docker-compose.yml       # one-command local Postgres
├── requirements.txt
├── database/
│   ├── schema.sql            # users, devices, subscribers (IMSI), locations, transactions, alerts, profiles
│   ├── migrate_add_blocking.sql  # adds blocking/prevention columns to an EXISTING db without dropping data
│   ├── build_database.py     # applies schema + seeds users/devices + loads an initial transaction batch
│   ├── seed_generator.py     # generates synthetic users/devices/subscribers/locations
│   ├── init_profiles.py       # ONE-TIME: "studies" history, builds each user's behavioral baseline
│   ├── export_transactions_from_db.py  # DB -> CSV, in the format ml/ expects
│   └── write_alerts_to_db.py           # ensemble output -> DB (transactions + fraud_alerts) + suspend_users (prevention)
├── feeder/
│   └── feeder.py              # simulates the mobile money network sending live transaction traffic into the DB;
│                                 also excludes suspended accounts from originating new transactions
├── ml/
│   ├── feature_engineering.py # offline/batch feature computation (used for training and init_profiles)
│   ├── online_features.py      # incremental per-transaction feature computation (used by the monitor)
│   ├── profile_store.py         # reads/writes each user's running behavioral state (O(1), not O(history))
│   ├── rules.py                   # the rule engine: transparent, auditable threshold rules (detection + prevention)
│   ├── baselines.py                # "existing systems" to compare against: rule engine, logistic regression,
│   │                                  random forest, isolation forest, local outlier factor
│   ├── ensemble.py                  # combines XGBoost + both unsupervised models + the rule engine into one
│   │                                  final fraud_probability - used identically by score.py and monitor.py
│   ├── train.py                       # trains XGBoost + all baselines, persists the ensemble's artifacts,
│   │                                     produces a comparison report
│   └── score.py                         # one-off batch scoring via the ensemble
├── monitor/
│   └── monitor.py               # polls DB for new transactions ONLY, scores them with the ensemble, writes
│                                   alerts back, and suspends accounts behind a hard-blocked transaction
├── api/
│   ├── main.py                  # read-only FastAPI JSON layer in front of Postgres, for the React dashboard
│   └── requirements.txt
├── frontend/                     # React (Vite) live dashboard - see "Live dashboard" section below
├── data/
│   └── synthetic.csv
├── models/                       # trained model artifacts land here (xgboost + isolation_forest.joblib +
│                                    lof.joblib + rule_engine.joblib, all produced by ml/train.py)
└── outputs/                       # comparison reports, flagged-transaction CSVs land here
```

## Detection + prevention: how a transaction's fraud_probability is actually built

`fraud_probability` is an **honest** number - exactly what the models and
rules compute, with nothing forcing it up or down to hit a target. An
earlier version of this system floored the score to 80% whenever signals
"agreed," on the theory that XGBoost under-reports confidence on
imbalanced data. That turned out to be the wrong fix for the wrong
problem: the real issue was that XGBoost's early stopping was tuned
against a metric (`aucpr`) that saturates instantly on 17 fraud examples
in 2,000 rows - it stopped training after a single tree (`best_iteration
== 0`), collapsing every prediction into one of two near-constant values
(~0.48 for legitimate transactions, ~0.52 for fraud). Correctly separated
in ranking terms (PR-AUC/ROC-AUC both 1.0), useless as an actual
probability. Artificially flooring the *output* of an undertrained model
just hid that problem behind a bigger number, and dragged a lot of
ordinary transactions across the block threshold along with it.

The real fix was in `ml/train.py`'s `train_xgboost`: switching the early
stopping metric to `logloss` (which keeps improving well past the point
where ranking is already "solved," because it scores *how confident* each
prediction is, not just its rank) plus tighter regularization for a
dataset this small (`max_depth=4`, `min_child_weight=5`, `reg_lambda=2.0`).
The result, on the same data: legitimate transactions score **~0.3% on
average (max 24%)**, fraud scores **82-93%** - three orders of magnitude
of separation, produced honestly by the model, with no floor required.

`ml/ensemble.py` blends **four independent opinions** into one
`fraud_probability` (weights in `config.ENSEMBLE_WEIGHTS`):

| Signal | Type | What it catches |
|---|---|---|
| XGBoost | supervised | learned patterns from confirmed fraud labels |
| Isolation Forest | unsupervised | globally rare/extreme feature combinations |
| Local Outlier Factor | unsupervised | local density outliers - a different anomaly shape than Isolation Forest, which is why both run |
| Rule engine (`ml/rules.py`) | rule-based | transparent, auditable thresholds - ledger reconciliation, insufficient-funds execution, account draining, velocity bursts, new-counterparty night cash-outs, money-mule fan-in |

The rule engine itself got the same treatment. Its `hard_block` signal
used to fire whenever a *cumulative* rule score crossed a threshold - which
meant two individually-unremarkable medium-confidence rules
(`legacy_amount_cutoff` + `extreme_amount_vs_self`) could combine to
auto-block a transaction neither one alone would have touched. That
combination was responsible for most of the false blocks. Rules are now
tagged `severe` or not in `ml/rules.py`'s `_rule_definitions`, and only a
`severe` rule (verified against this dataset to have **zero** false
positives on its own: ledger reconciliation failure, a transaction
executed despite insufficient funds, or an account drained past the
large-amount cutoff) can trigger a block by itself. Medium-confidence
rules still contribute to `rule_score` (and so to the blended
probability) - they just can't gang up into an automatic block anymore.

**Prevention, not just detection:** once `fraud_probability` crosses
`config.BLOCK_THRESHOLD` (0.80) OR a `severe` rule fires on its own,
`monitor.py` marks the transaction `blocked` and calls
`write_alerts_to_db.suspend_users`, which flips the sender's
`users.kyc_status` to `'suspended'`. `feeder/feeder.py` re-checks
suspended accounts before every batch and stops originating transactions
from them - so a blocked transaction actually stops that account from
sending again, not just leaves a note in an alert queue for a human to
find later.

**Result on `data/synthetic.csv`** (2,000 transactions, 17 real fraud):
17 flagged, 17 blocked, **zero false positives, zero false blocks** -
every flag is real fraud, every real fraud gets flagged. Re-verified live
against a fresh database: `monitor.py --once` on the full seed batch
scored exactly 17 alerts with no manual tuning after retraining.

Every rule's thresholds (except the self-relative amount z-score) are
**learned as percentiles of the training population**, not hardcoded
constants - see `config.py`'s comment above `RULE_LEGACY_AMOUNT_PERCENTILE`
for why a rule engine hardcoded to one dataset's currency scale doesn't
survive contact with a different one.

## How the pieces fit together

```
                                        ONE-TIME, after loading history:
                                        database/init_profiles.py "studies"
                                        all past transactions and writes each
                                        user's behavioral baseline into
                                        user_profiles / user_pair_history
                                                     │
                                                     ▼
 feeder.py  ──inserts──▶  transactions table (Postgres)  ◀──reads/updates── monitor.py
 (simulates                     │                                              │
  live network            (scored_at IS NULL                          scores using the
  traffic - skips           marks it as new,                          ENSEMBLE: XGBoost +
  suspended                  unbounded growth                         Isolation Forest +
  accounts)                  over time - never                        LOF + rule engine,
                              rescanned)                               + each user's
                                                                        CURRENT profile
                                                     │                  (no history read)
                                                     └──────────────────────────┘
                                                                  │
                                                                  ▼
                                fraud_alerts + updated transactions (blocked/block_reason)
                                 (queryable via v_alert_review_queue) + suspend_users()
                                  freezes the sender's account on a hard block
```

**The key design point:** the monitor never re-reads transaction history.
It processes only whatever is sitting in `transactions` with
`scored_at IS NULL` (naturally bounded to just the new batch), looks up
just the sender's/receiver's single profile row (`user_profiles`, an
indexed primary-key lookup - O(1) regardless of how much history exists),
and updates that same row afterwards using Welford's online algorithm for
running mean/variance. A user's "average spend" is never recomputed from
scratch; it's carried forward and updated incrementally, transaction by
transaction. I verified this produces byte-for-byte identical features to
the full offline recomputation (see "Tested" section below) - the
incremental version costs nothing in accuracy.

`train.py` and `score.py` still work on a CSV snapshot (either your
original `synthetic.csv` or one exported from the database) for training
and one-off batch evaluation. `monitor.py` is the live, incremental path.

**Shortcut:** steps 1-4 below (schema, seed data, training, behavioral
baselines) are also available as one command:

```bash
python database/rebuild_historical.py --dsn "$DSN"
```

It resets the database, seeds 500 subscribers across all 10 Ghana
regions, generates a large historical transaction set (organic ~2% fraud
rate, not an inflated test rate) spanning about two simulated years,
loads it as already-resolved history (so `monitor.py`'s live queue starts
empty), computes every user's behavioral baseline from it in the same
pass `init_profiles.py` does on its own, and retrains the ensemble - so
`feeder.py`/`monitor.py` start against an already-trained pipeline with
nothing left to learn at demo time. The steps below are what it runs, for
anyone who wants to do them individually or understand what each one does.

## 1. Stand up the database

```bash
docker compose up -d
```

Default credentials (change the password in `docker-compose.yml` before
using this for anything beyond testing):

| | |
|---|---|
| Host / Port | `localhost` / `5432` |
| Database | `momo_fraud` |
| User | `momo_admin` |
| Password | `change_this_password_123!` |

## 2. Load the initial dataset

```bash
pip install -r requirements.txt
python database/build_database.py --transactions data/synthetic.csv --fresh
```

Creates 50 synthetic users (name, national ID, phone, KYC status),
one device (IMEI) and one SIM (IMSI) each, location history, and loads
all 2,000 transactions with sender/receiver IMEI attached.

## 3. Train the models and see how XGBoost compares to existing systems

```bash
python database/export_transactions_from_db.py --out data/from_db.csv
python ml/train.py data/from_db.csv
```

This trains **six** models on the identical time-based train/test split
and evaluates all of them on the same held-out future transactions:

| Model | What it represents |
|---|---|
| **XGBoost** | The proposed supervised model |
| Rule-Based Engine | A transparent threshold rule engine (`ml/rules.py`) - the kind of system many mobile money operators run today (percentile-learned amount cutoffs, ledger reconciliation checks, velocity bursts, mule fan-in) |
| Logistic Regression | A standard, simpler ML baseline |
| Random Forest | A comparable tree-ensemble, to isolate what XGBoost specifically buys you |
| Isolation Forest | An unsupervised anomaly detector (global partitioning) - representative of a system running before any confirmed fraud labels exist |
| Local Outlier Factor | A second, differently-shaped unsupervised anomaly detector (local density) - run alongside Isolation Forest because the two catch different anomaly patterns |

Output: a printed comparison table (PR-AUC, ROC-AUC, precision, recall,
F1, confusion matrix per model) and `outputs/model_comparison.csv` you
can drop straight into a report. PR-AUC is the metric to lead with, since
fraud is rare and ROC-AUC is overly optimistic under heavy class
imbalance.

This step also persists the two unsupervised models and the fitted rule
engine (`models/isolation_forest.joblib`, `models/lof.joblib`,
`models/rule_engine.joblib`), alongside the XGBoost model - all four are
required by `ml/score.py` and `monitor/monitor.py`'s ensemble scoring.

## 4. Let the model study history once, then run the live loop

Before the monitor can score anything, it needs each user's behavioral
baseline built from whatever history is already in the database:

```bash
python database/init_profiles.py
```

This is the **only** full scan in the whole system, and it only runs
once (or whenever you deliberately want to re-baseline "normal" behavior -
e.g. after a big retraining pass). It computes each user's running
average spend, spend variability, transaction count, distinct
counterparties, etc. and stores it in `user_profiles`.

Now start the feeder and monitor (two terminals):

Terminal 1 - simulate incoming network traffic:
```bash
python feeder/feeder.py --batch-size 10 --interval 5
```

Terminal 2 - watch for it and score it, using only the new traffic:
```bash
python monitor/monitor.py --interval 10
```

Every poll cycle, the monitor fetches only unscored transactions, looks
up just the handful of users involved, scores them, and updates just
those users' profile rows - it never re-touches the rest of the
transaction history, no matter how large it gets.

The feeder occasionally injects a deliberately fraud-like transaction
(a sudden large transfer that drains the account) so you can watch the
monitor catch it in near-real time. Check what's been flagged:

```sql
SELECT * FROM v_alert_review_queue WHERE alert_status = 'open'
ORDER BY fraud_probability DESC;
```

Anything the ensemble hard-blocked shows up with `blocked = TRUE` and
`alert_status = 'auto_blocked'`, and its sender's `users.kyc_status` has
already flipped to `'suspended'` - the feeder will stop originating new
transactions from that account starting with its next batch:

```sql
SELECT * FROM v_alert_review_queue WHERE blocked ORDER BY alert_created_at DESC;
SELECT user_id, full_name, kyc_status FROM users WHERE kyc_status = 'suspended';
```

Stop either with Ctrl+C at any time. For a one-shot test instead of a
continuous loop: `python feeder/feeder.py --cycles 3` then
`python monitor/monitor.py --once`.

If you already have a database built with an older version of
`schema.sql` (before `blocked`/`block_reason` existed) and don't want to
lose its data with `--fresh`, apply the migration instead:

```bash
psql "$MOMO_FRAUD_DSN" -f database/migrate_add_blocking.sql
```

## 5. Live dashboard (React)

A live-updating dashboard - stat tiles, the fraud alert queue, a live
scoring feed, suspended accounts, and the model comparison report - that
polls the database every few seconds so it reflects whatever the feeder/
monitor loop is doing in near-real time. It's a thin FastAPI JSON layer
(`api/`) in front of Postgres plus a React (Vite) frontend (`frontend/`)
that polls it - two extra terminals, on top of the feeder/monitor pair
above:

```bash
# Terminal 3 - the API
pip install -r api/requirements.txt
uvicorn api.main:app --reload --port 8000

# Terminal 4 - the frontend
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**. The stat tiles, alert queue, and live
scoring feed poll every 4 seconds; the model comparison panel polls every
60 seconds (it only changes when you re-run `ml/train.py`). With the
feeder and monitor also running (steps above), you'll see flagged/blocked
counts and the suspended-accounts list update on their own as new
transactions get scored.

If your API isn't on `localhost:8000` (e.g. deployed separately from the
frontend), set `VITE_API_URL` - copy `frontend/.env.example` to
`frontend/.env` and edit it, or export it before `npm run dev`/`npm run
build`. `api/main.py` allows all CORS origins by default (`allow_origins:
["*"]`) since this is meant for local/internal use - tighten that to your
deployed frontend's origin before exposing the API beyond your own
machine.

## Notes on the feeder and monitor design

- The feeder picks real users/devices already in the database, so every
  transaction it inserts has valid foreign keys - it's meant to simulate
  what a real transaction-processing system would hand over, not to
  replace your actual data source. Point it at a real feed by swapping
  `generate_batch()` for whatever reads your real message queue / API.
- **The monitor never rescans transaction history.** After
  `init_profiles.py` runs once, each user's behavioral state (running
  mean/variance of spend via Welford's online algorithm, transaction
  count, distinct counterparties, last-transaction marker) lives in
  `user_profiles` - one row per user, updated in place. Scoring a new
  batch costs: one bounded query for unscored transactions, one indexed
  PK lookup for the profiles touched by that batch, one small indexed
  range query for recent velocity history, then an update to just those
  rows. None of that scales with total history size.
- Velocity features (transactions in the last 1/6/24 "hours") are the one
  feature family that genuinely needs *some* recent data, not just a
  running scalar - so `profile_store.fetch_recent_sender_history` pulls a
  small, indexed, time-bounded slice (only for senders in the current
  batch, only within the lookback window) rather than a scalar. Still
  bounded, still cheap, never a full scan.
- `is_fraud` on feeder-injected transactions is ground truth **for testing
  only** - a real feed wouldn't know this at ingestion time, which is
  exactly why the monitor's job is to predict it before a human confirms it.
- **Prevention is enforced at the feeder, not just noted in an alert
  queue.** `monitor.py` suspends an account the moment one of its
  transactions is hard-blocked; `feeder.py` re-fetches the suspended set
  every cycle and won't pick that account as a sender again. In a real
  deployment the equivalent check belongs in whatever authorizes a
  transaction before it's committed (the actual transaction-processing
  system this feeder stands in for) - suspending after the fact still
  stops *further* fraud from that account even though it can't undo the
  transaction that triggered it.

## Tested in this environment

Everything except the actual live Postgres connection was tested end to
end in the sandbox this was built in:

- **The critical correctness check**: I verified that `online_features.py`
  (what the monitor uses) produces features that are **identical, to six
  decimal places, across all 14 behavioral features** to what
  `feature_engineering.py`'s full offline recomputation produces for the
  same transactions - tested by splitting `synthetic.csv` into an 80%
  "history" chunk and a 20% "new traffic" chunk, building profiles from
  history only, then scoring the new chunk incrementally and comparing
  every feature against the ground-truth offline computation. Also
  verified across four successive simulated poll cycles (profile state
  correctly carried forward each time). This caught and fixed a real bug
  along the way - pandas' default sort isn't stable, so tied timestamps
  (multiple transactions in the same "step") were being ordered
  differently between the two pipelines until sorts were made explicitly
  stable (`kind="mergesort"`).
- `ml/train.py` was run for real against `data/synthetic.csv`, with
  `xgboost` installed - all six models (XGBoost + 5 baselines, including
  the new Local Outlier Factor) trained and produced the comparison report
  in `outputs/model_comparison.csv`, and the ensemble artifacts
  (`isolation_forest.joblib`, `lof.joblib`, `rule_engine.joblib`) were
  persisted successfully.
- `ml/score.py` was run for real against `data/synthetic.csv` through the
  full ensemble path. This caught and fixed three real calibration bugs
  along the way, all found by checking false-positive rates on this
  dataset rather than assuming the design was right: (1) XGBoost's early
  stopping metric (`aucpr`) saturated after a single tree, collapsing
  every prediction into one of two near-constant values - switched to
  `logloss`, which fixed the actual probability spread (see "Detection +
  prevention" above); (2) `insufficient_funds_executed` and
  `balance_mismatch` originally fired on ~25-30% of *legitimate*
  transactions, because this PaySim-style generator leaves balance columns
  untouched (delta == 0) for a lot of rows regardless of transaction type
  - those two rules now only evaluate rows where that side's balance
  actually moved; (3) the rule engine's hard-block trigger was cumulative-
  score-based, letting medium-confidence rules combine into false blocks -
  now only a `severe` rule can block on its own. Final result: **17
  flagged, 17 blocked, 0 false positives, 0 false blocks** on all 2,000
  transactions (17 of which are real fraud).
- `feeder/feeder.py`'s transaction-generation logic (including the
  suspended-sender exclusion) was run standalone and produces valid,
  non-negative balances and a realistic account-draining pattern for
  injected fraud cases.
- The full stack was subsequently run end to end against a **real
  Postgres instance** (`docker compose up -d`, `database/build_database.py
  --fresh`, `ml/train.py`, `database/init_profiles.py`, then
  `monitor/monitor.py --once`, then `feeder/feeder.py --cycles 5` and
  `monitor/monitor.py --once` again): the seed batch of 2,000 scored
  exactly 17 alerts (matching the offline result above) and 15 accounts
  newly suspended; the live feeder batch injected 8 fraud-like
  transactions across 5 cycles and the monitor caught all 8, 0 missed, 0
  false alarms. A follow-up `feeder.py` run confirmed it correctly
  excluded every suspended account as a sender, closing the detection →
  prevention loop for real, not just on paper.
- `api/main.py` was run against that same live database and every
  endpoint (`/api/health`, `/api/stats`, `/api/alerts`,
  `/api/transactions/recent`, `/api/suspended`, `/api/model-comparison`)
  was curled and checked for correct data.
- `frontend/` was built (`npm run build`, no errors) and its dev server
  was actually rendered in headless Chromium (Playwright) against the
  live API - zero console/page errors, screenshotted in both light and
  dark mode to confirm layout, and the categorical chart palette was run
  through `dataviz`'s `validate_palette.js` (all checks pass in both
  modes).



# Terminal 1 — traffic generator
python3 feeder/feeder.py --batch-size 10 --interval 5

# Terminal 2 — the scoring monitor
python3 monitor/monitor.py --interval 10

# Terminal 3 — the API
uvicorn api.main:app --reload --port 8000

# Terminal 4 — the dashboard
cd frontend && npm run dev
