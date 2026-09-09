# Mobile Money Fraud Detection System — Abstract & Executive Summary

Group 13. Companion to [README.md](../README.md) and
[DOCUMENTATION.md](../DOCUMENTATION.md).

Two documents follow. The **abstract** is the ~250-word academic framing to
put at the front of the report or to open the presentation with. The
**executive summary** is the two-page version for a reader who will not open
the codebase.

---

## Abstract

Mobile money is now the dominant channel for retail payments across much of
sub-Saharan Africa, and the fraud that follows it — account takeover, SIM-swap
drains, structuring, and money-mule fan-in — is detected today largely by
fixed-threshold rule engines that operators can audit but that catch only a
fraction of what passes through them. This work presents an end-to-end fraud
detection and *prevention* system for a mobile money network, built on
PostgreSQL with a supervised gradient-boosted classifier (XGBoost) at its
centre, and evaluates it against five alternative systems on an identical
time-based train/test split of 60,000 synthetic transactions.

On a held-out window of 12,000 future transactions containing 668 fraudulent
ones (5.6%), XGBoost reaches a precision–recall AUC of 0.858 and recovers
86.2% of fraud at 64.4% precision. The threshold rule engine representing
current operator practice is far more precise (96.3%) but recovers only 15.7%
of the same fraud — it misses roughly five of every six fraudulent
transactions. Precision–recall AUC is reported in preference to ROC-AUC, which
is optimistically flat (0.70–0.99) across all six models under this class
imbalance.

The deployed system does not use XGBoost alone. A weighted ensemble blends the
supervised model with two unsupervised anomaly detectors and the rule engine,
producing a calibrated probability that drives a two-stage response: alert for
review above 0.50, and automatic block plus sender suspension above 0.80 or on
any single high-confidence rule. A live loop — traffic simulator, incremental
scorer, and dashboard — demonstrates the pipeline operating on streaming
traffic without ever rescanning transaction history.

*(≈270 words. Trim the final paragraph to ~200 if a hard limit applies.)*

---

## Executive Summary

### The problem

Mobile money operators sit on a structural detection gap. Their existing
controls are threshold rules — flag anything over X, flag more than N
transactions per hour — because rules are auditable and an operations team can
defend every alert to a regulator. The cost of that auditability is recall.
Measured directly in this project, a well-tuned rule engine with twelve rules
and population-learned cutoffs achieves **96.3% precision but 15.7% recall**:
almost everything it flags is genuinely fraud, and it silently passes five of
every six fraudulent transactions through to settlement.

The gap is not a tuning problem. Loosening the thresholds trades the precision
away without recovering the missed cases, because the missed cases are not
extreme on any single axis — they are ordinary-looking amounts from a sender
whose *own* behaviour has changed.

### What was built

A complete detection-and-prevention pipeline, not a model in a notebook:

| Layer | Component |
|---|---|
| Store | PostgreSQL 16 — subscribers, devices (IMEI), SIMs (IMSI), location history, transactions, alerts, per-user behavioural profiles |
| Features | Offline batch engineering for training; a separate incremental path that computes the same features per transaction in O(1) against a stored profile |
| Detection | XGBoost, plus Isolation Forest, Local Outlier Factor, and a twelve-rule engine |
| Decision | Weighted ensemble → one `fraud_probability` |
| Prevention | Automatic block and sender suspension, enforced at origination |
| Operations | Traffic simulator, incremental monitor, read-only FastAPI layer, React dashboard |

### Results

Six systems, one identical time-based split — trained on earlier
transactions, evaluated on a held-out window of 12,000 later ones. Full table
in [outputs/model_comparison.csv](../outputs/model_comparison.csv).

| System | PR-AUC | Precision | Recall | F1 |
|---|---|---|---|---|
| **XGBoost (proposed)** | **0.858** | 0.644 | **0.862** | **0.738** |
| Logistic Regression | 0.843 | 0.453 | 0.949 | 0.613 |
| Random Forest | 0.842 | 0.924 | 0.457 | 0.611 |
| Isolation Forest (unsupervised) | 0.398 | 0.260 | 0.430 | 0.324 |
| Rule engine (current practice) | 0.312 | 0.963 | 0.157 | 0.270 |
| Local Outlier Factor (unsupervised) | 0.056 | 0.054 | 0.599 | 0.099 |

Three findings worth stating plainly:

1. **XGBoost's advantage is recall at usable precision.** It recovers 86.2% of
   fraud where the rule engine recovers 15.7% — a 5.5× improvement in fraud
   caught — while still flagging fewer than 3% of legitimate transactions.
2. **The comparison is honest about its margins.** Logistic Regression and
   Random Forest land within 0.02 PR-AUC of XGBoost. The tree ensembles differ
   not in aggregate quality but in *operating point*: Random Forest is a
   high-precision/low-recall system much like the rule engine, and Logistic
   Regression the reverse. XGBoost is the only model that is strong on both
   sides simultaneously, which is what makes it deployable without a second
   system behind it.
3. **ROC-AUC would have hidden all of this.** Every supervised model scores
   0.985–0.987 ROC-AUC. Under 5.6% fraud prevalence that metric is close to
   uninformative, which is why precision–recall AUC leads the report.

### From score to action

The production path blends four independent opinions rather than trusting one
model: XGBoost at weight 0.55, the two unsupervised detectors at 0.15 each,
and the rule engine at 0.15. The unsupervised models contribute because they
require no labels — they represent what the system can detect before any fraud
has been confirmed — and the rule engine contributes because it keeps a
human-readable justification attached to every alert.

The resulting probability is deliberately left uncalibrated by any floor or
target. An earlier iteration forced scores to 80% whenever signals agreed; that
was removed, because a transaction scoring 55% needs to *mean* genuinely
ambiguous for a reviewer to triage it correctly.

Two thresholds turn the score into a decision:

- **≥ 0.50 — alert.** The transaction enters a review queue with the
  contributing rules named in plain language.
- **≥ 0.80, or any one severe rule — block.** The transaction is marked
  blocked and the sender's KYC status flips to `suspended`, after which the
  network stops accepting that account as an originator. Four of the twelve
  rules qualify as severe on their own: ledger reconciliation failure, a
  transaction executed against insufficient funds, an account drained past the
  99th-percentile amount, and a large cash-out within 24 hours of a device
  change (the SIM-swap playbook). Each fires on zero legitimate transactions
  in this dataset.

This is the distinction between detection and prevention, and it is the part a
rules-only system cannot safely do: blocking requires a signal precise enough
that a false positive is rare enough to accept.

### Operating characteristics

- **The monitor never rescans history.** Each cycle fetches only unscored
  transactions and updates only the profiles of the users involved. Cost per
  cycle is a function of new traffic, not accumulated volume — the property
  that makes the design plausible at telco scale.
- **One full scan, once.** Behavioural baselines are built by a single
  historical pass at setup, then maintained incrementally.
- **Traffic is adversarial by construction.** The simulator injects five
  distinct fraud typologies — outright drain, SIM-swap-then-drain, structuring
  into sub-threshold amounts, rapid fan-out across mule accounts, and dormant
  account reactivation — so the live loop is tested against patterns shaped
  differently from one another.
- **Location is an attribution layer, not a detection signal.** The system
  stores each subscriber's location history and current position, and the API
  derives distance-from-home and a resolved street-level address for
  investigators. No rule or model currently consumes it; it answers *where did
  this happen* after a flag, not *is this fraud*.

A representative run on a freshly built database: 2,249 transactions scored,
95 alerts raised, 17 transactions hard-blocked, and 20 of 100 accounts
suspended.

### Limitations

Stated deliberately, because they bound what the results support:

- **The data is synthetic.** Fraud labels are known by construction, which
  makes every metric above an upper bound. Real fraud labels arrive late,
  incompletely, and sometimes wrongly.
- **The SIM-swap rule is easy in this dataset.** Legitimate device changes are
  not simulated at all, so the rule's perfect separation reflects the
  generator, not the world. On real traffic it would need re-fitting against
  genuine handset-upgrade behaviour.
- **The unsupervised models are weak individually.** Local Outlier Factor is
  near chance (PR-AUC 0.056). Their contribution is diversity within the
  ensemble, not standalone capability, and the 0.15 weights reflect that.
- **No concept-drift handling.** Fraud tactics move; the model is retrained
  manually. Scheduled retraining and drift monitoring are the obvious next
  step, alongside feeding location into detection as an
  impossible-travel signal.

### Conclusion

The system demonstrates that the precision-versus-recall tradeoff operators
currently accept is not necessary. A gradient-boosted model recovers 5.5× more
fraud than the threshold approach at precision that remains operationally
usable, and wrapping it in an ensemble with rule-based and unsupervised signals
preserves the auditability that made rules attractive in the first place —
every alert still carries a named, human-readable reason. Coupled with
automatic blocking at high confidence, the result moves the intervention point
from *after settlement* to *before it*.
