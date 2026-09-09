# Mobile Money Fraud Detection System — Functional Requirements, Technology Stack & Implementation

Group 13. Companion to [README.md](../README.md) (setup/run) and
[DOCUMENTATION.md](../DOCUMENTATION.md) (deep technical reference). This
document exists to support hosting/deployment planning and to explain the
system to a non-technical stakeholder (an ISP/MNO evaluating it) — it
describes what the system *must do*, what it's *built with*, and *why an
ISP would want it*, all grounded in what is actually implemented and
running, not a proposal.

---

## 1. Functional System Requirements

### 1.1 Transaction ingestion & scoring

| ID | Requirement |
|---|---|
| FR-1 | The system shall accept a continuous stream of mobile money transactions (sender, receiver, amount, type, device/IMEI, timestamp) and persist each one before scoring it. |
| FR-2 | The system shall compute a fraud probability for every transaction within milliseconds of ingestion, using only the sender/receiver's already-known behavioral state — never rescanning full transaction history to score one new transaction. |
| FR-3 | The system shall blend four independent detection signals (a supervised classifier, two unsupervised anomaly detectors, and a rule engine) into one probability, so a fraud pattern only has to trip one detector to be caught, and a legitimate transaction has to fool all four to pass unflagged. |
| FR-4 | The system shall maintain each subscriber's behavioral baseline (average spend, spend variability, transaction count, distinct counterparties, device history) incrementally, updated after every transaction, not recomputed from scratch. |

### 1.2 Decision & prevention

| ID | Requirement |
|---|---|
| FR-5 | Every scored transaction shall resolve to exactly one of three outcomes: **auto-approved** (no review needed), **flagged** (queued for analyst review), or **blocked** (transaction stopped and the sender's account suspended) — never left in an undefined state. |
| FR-6 | The system shall automatically suspend an account the moment one of its transactions is blocked, and shall refuse to originate further transactions from a suspended account until a human reviews it. |
| FR-7 | Every flag or block shall carry a specific, human-readable reason (which rule fired, or which threshold was crossed) — never an unexplained score. |
| FR-8 | Suspension shall be reversible (a status flag, not a destructive action) so a human reviewer can clear a false positive. |

### 1.3 Analyst-facing operations

| ID | Requirement |
|---|---|
| FR-9 | The system shall provide a live, auto-refreshing dashboard showing system health, active alerts, fraud volume, scoring latency, and auto-approval volume. |
| FR-10 | The system shall let an analyst search and retrieve any subscriber's full profile — identity, KYC status, device, current/home location, behavioral baseline, and recent transaction history — by name, subscriber ID, or phone number. |
| FR-11 | The system shall let an analyst search and retrieve any individual transaction's full detail, including the specific reasoning behind its score. |
| FR-12 | The system shall plot the current vs. home location of the highest-risk subscribers on a map, so geographic anomalies (a transaction far from a subscriber's normal range) are visible at a glance. |
| FR-13 | The system shall generate on-demand reports for a selectable date range (today / 7 days / 30 days / all time), including a rule-firing breakdown and an exportable CSV. |
| FR-14 | The system shall maintain a queryable audit log of every scored transaction and every decision made on it. |

### 1.4 Access control

| ID | Requirement |
|---|---|
| FR-15 | The system shall require authentication before any operational data is served — every data endpoint shall reject requests without a valid session, enforced server-side, not only hidden in the UI. |
| FR-16 | Sessions shall expire after a configurable period and shall be individually revocable (logout). |

### 1.5 Training & retraining

| ID | Requirement |
|---|---|
| FR-17 | The system shall support retraining its detection models against a historical transaction dataset on demand, without requiring code changes. |
| FR-18 | The system shall report each model's precision, recall, F1, and PR-AUC on a held-out, time-based split (train on past, test on future) so performance claims reflect real generalization, not in-sample fit. |
| FR-19 | Rule thresholds shall be learned from the training population's own statistical distribution (percentiles), not hardcoded constants, so the same rule engine adapts to a different deployment's transaction volumes and currency scale. |

### 1.6 Non-functional requirements

| ID | Requirement |
|---|---|
| NFR-1 | **Performance** — scoring a batch of new transactions shall cost a bounded number of indexed queries, independent of total historical transaction volume. |
| NFR-2 | **Scalability** — the data model shall support growing the subscriber base without re-architecting (demonstrated: 100 → 500 subscribers with zero schema change). |
| NFR-3 | **Availability** — a transient database connection failure shall be retried automatically before surfacing an error to the client. |
| NFR-4 | **Auditability** — every automated decision (approve/flag/block) shall be traceable to a specific reason and timestamp. |
| NFR-5 | **Portability** — the system shall run against any standard PostgreSQL 13+ instance, local or managed, without code changes (only a connection string). |

---

## 2. Technology Stack

| Layer | Technology | Role |
|---|---|---|
| Database | **PostgreSQL 16** (managed: Neon serverless; local: Docker) | System of record — subscribers, devices (IMEI), SIMs (IMSI), location history, transactions, alerts, behavioral profiles. |
| Backend API | **FastAPI** (Python), **Uvicorn** (ASGI server) | Thin, read-mostly JSON API in front of Postgres; owns authentication and connection pooling. |
| DB driver | **psycopg2** (`ThreadedConnectionPool`) | Pre-warmed connection pool — avoids paying a fresh TLS handshake (>1s against a managed/serverless DB) per request. |
| ML / detection | **XGBoost**, **scikit-learn** (Isolation Forest, Local Outlier Factor, Logistic Regression, Random Forest baselines), **NumPy**, **pandas** | The ensemble's four detection signals plus the baseline comparison suite. |
| Model persistence | **joblib**, XGBoost's native JSON format | Trained models are serialized to disk and loaded once at process startup, not retrained per request. |
| Live traffic / scoring loop | Plain Python (`feeder/`, `monitor/`) | Simulates/ingests live transactions and runs the incremental scoring loop — no separate message queue or stream processor needed at this scale. |
| Frontend | **React 19**, **Vite 8** | Single-page analyst dashboard; no router or global state library — plain `useState`/custom hooks (`usePolling`) are sufficient for this app's size. |
| Mapping | **Leaflet** + OpenStreetMap tiles | Geographic visualization of subscriber location vs. home range. |
| Auth | Custom bearer-token sessions, **SHA-256** password hashing (`hashlib`), constant-time comparison (`hmac.compare_digest`) | No third-party auth dependency; deliberately minimal for this deployment's scale. |
| Reporting | **reportlab**, **matplotlib**, **python-docx** | Generates the PDF/DOCX comparison and defense documents from live data (`defense/`). |

---

## 3. How It's Implemented

### 3.1 Data flow

```
feeder.py  ──inserts──▶  transactions (Postgres)  ◀──reads/scores── monitor.py
(live traffic,                  │                                        │
 or a real transaction    scored_at IS NULL                    ensemble = XGBoost (55%)
 gateway in production)    marks a row "pending"              + Isolation Forest (15%)
                                                                  + LOF (15%) + rules (15%)
                                                                        │
                                                          fraud_probability, flagged,
                                                          blocked, auto_approved written
                                                          back to the same row
                                                                        │
                                                          block? → suspend sender's
                                                          account (feeder stops
                                                          selecting it as a sender)
                                                                        │
                                                          api/main.py serves all of
                                                          the above as JSON, behind
                                                          require_auth on every route
                                                                        │
                                                          React dashboard polls every
                                                          4s (only for panels on the
                                                          active page)
```

### 3.2 Detection pipeline

Every transaction is converted to ~25 behavioral/transactional features
(amount, log-amount, balance deltas and reconciliation, time-of-day,
velocity over 1h/6h/24h windows, distinct-counterparty counts, device
change recency) computed **causally** — only from what was already known
before this transaction, exactly matching what the live incremental path
can compute with no future information. The same feature function is used
for offline training and live scoring, so there is no train/serve skew.

- **XGBoost (55% weight)** — the primary supervised model, trained on
  labeled historical fraud.
- **Isolation Forest (15%)** and **Local Outlier Factor (15%)** —
  unsupervised; catch a fraud pattern the first time it's ever seen, with
  no confirmed label required. Two different anomaly shapes (global
  partitioning vs. local density) are run because neither reliably covers
  the other's blind spot alone.
- **Rule engine (15%)** — a transparent, auditable set of threshold rules
  (ledger mismatch, velocity bursts, structuring, dormant-account
  reactivation, mule fan-in, SIM-swap-then-drain) whose cutoffs are
  *learned as percentiles of the training population*, not hardcoded, so
  the same rules work at a different deployment's transaction scale.

The four scores are blended into one `fraud_probability`. Above 0.50 the
transaction is flagged for review; above 0.80, or if a single high-
confidence rule fires on its own, it's blocked and the sender suspended
automatically — no human has to act for prevention to happen.

### 3.3 Data model highlights

Device (IMEI) and SIM/subscriber identity (IMSI) are modeled as **separate
entities linked over time** — matching how a real mobile network works: a
person can swap SIMs into the same phone or move their SIM into a new
phone, and either is a classic fraud signal (SIM-swap fraud, device
cloning) that a simpler "one identity per user" schema would silently
discard.

### 3.4 Frontend

A single-page app behind a real login gate (`/api/login` issues a bearer
token verified server-side on every subsequent call). Pages: Dashboard,
Alerts, Accounts (suspended), Subscribers (search + full profile), Map,
Reports, System Log. Each page's data only polls while that page is
actually visible, keeping steady-state load bounded regardless of how
many pages exist.

### 3.5 Deployment shape (for hosting)

Three independently deployable pieces:

1. **Database** — any PostgreSQL 13+ (currently Neon, a serverless
   managed Postgres; a self-hosted instance or another managed provider
   works identically since access is a plain connection string).
2. **API** — a single Python/FastAPI process (`uvicorn api.main:app`);
   stateless except for the in-memory session table, so it can run behind
   a load balancer with sticky sessions, or be swapped to a shared session
   store (Redis) for true horizontal scaling.
3. **Frontend** — a static build (`npm run build`) servable from any
   static host or CDN, pointed at the API via `VITE_API_URL`.

The feeder and monitor are operational background processes, not
user-facing services — in a real deployment, the feeder's role is played
by the ISP's actual transaction-authorization system, and the monitor
runs as a long-lived worker process or scheduled job.

---

## 4. Why an ISP / Mobile Network Operator Would Use This System

Mobile money is run by MNOs (MTN, Vodafone, AirtelTigo, and equivalents
elsewhere) on their own network infrastructure — they are the one party
positioned to see the full signal this system is built around: which SIM
is in which device, where a subscriber's phone actually is, and every
transaction as it happens. A third-party fraud vendor sitting outside the
network sees only the transaction; the network operator sees the
transaction **and** the device and SIM history behind it.

1. **Prevention, not just detection.** Most fraud tooling produces a
   report for tomorrow's review meeting — by then the money is gone. This
   system suspends a compromised account automatically, at the moment of
   the transaction that reveals it, using signal (device/SIM change,
   location jump) an MNO already has and an external vendor does not.

2. **Matches real SIM-swap and device-cloning fraud**, a leading fraud
   vector on mobile money networks specifically, because IMEI and IMSI
   are modeled as separate, linked entities — not collapsed into one
   generic "user" the way a generic banking fraud tool would.

3. **Regulator-defensible by design.** Central banks and telecom
   regulators (e.g. Bank of Ghana's mobile money guidelines) expect an
   auditable reason for every blocked transaction and every account
   action. Every decision this system makes traces to a named rule or a
   documented probability threshold — never an unexplained black-box
   score — which is exactly what a compliance audit or a customer dispute
   needs.

4. **Doesn't require a large confirmed-fraud dataset to start catching
   fraud.** The two unsupervised detectors work from day one, before an
   operator has accumulated enough confirmed cases to train a supervised
   model well — closing the "cold start" gap smaller operators or new
   markets face.

5. **Reduces analyst workload, not just fraud losses.** The explicit
   auto-approval pathway means an analyst team's queue holds only what
   actually needs a human look — not every transaction, and not an
   opaque "everything below the line is probably fine."

6. **Scales with the network, not against it.** Scoring cost is bounded
   by the size of the current batch, not by how much transaction history
   has accumulated — a design constraint that matters at MNO transaction
   volumes (millions of transactions per day) in a way it wouldn't for a
   small merchant.

7. **Owns its own data.** Running this in-house (or hosted under the
   operator's control) means subscriber transaction and location data
   never has to leave the operator's infrastructure to reach a
   third-party fraud-scoring service — a material data-sovereignty and
   compliance advantage over an external SaaS fraud vendor.
