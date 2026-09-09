# Defense Poster — Design Specification

Specifies the **A0 defense poster** for the Group 13 Mobile Money Fraud Detection
System: grid, panel-by-panel content, figure specs, and the visual system.

Unlike [`frontend/design.md`](../frontend/design.md), which documents a thing that already
exists, this is a **proposal to build from**. Nothing here is rendered yet.

Companion artifact to [`docs/build_defense_brief.py`](build_defense_brief.py) → the
`.docx` defense brief. The poster deliberately reuses that brief's palette so the two read
as one system in the same room.

---

## 1. Format & grid

**A0 portrait, 841 × 1189 mm**, printed. Three columns, top-down narrative
(problem → method → results → limitations → conclusion).

| | mm |
|---|---|
| Trim | 841 × 1189 |
| Margin (all sides) | 40 |
| Content area | 761 × 1109 |
| Columns | 3 × **237** |
| Gutter (h & v) | 24 |
| Bleed | 3 (if the printer requires it) |

### Panel grid

```
┌───────────────────────────────────────────────────────────┐
│ TITLE BAND                                    761 × 150   │
│   title + subtitle + authors            (95)              │
│   ── KPI STRIP: 4 tiles ──              (55)              │
├─────────────────┬─────────────────┬───────────────────────┤
│ P1 THE PROBLEM  │ P2 PIPELINE     │ P3 RESULTS            │
│                 │                 │   Fig 1 scatter       │
│      237 × 390  │      237 × 390  │   + 6-model table     │
│                 │                 │            237 × 390  │
├─────────────────┼─────────────────┼───────────────────────┤
│ P4 THREE        │ P5 ENSEMBLE &   │ P6 LIVE SYSTEM        │
│    SIGNALS      │    PREVENTION   │   screenshot +        │
│      237 × 285  │      237 × 285  │   loop evidence       │
│                 │                 │            237 × 285  │
├─────────────────┴─────────────────┼───────────────────────┤
│ P7 LIMITATIONS & FUTURE WORK      │ P8 CONCLUSION         │
│                        498 × 212  │            237 × 212  │
└───────────────────────────────────┴───────────────────────┘
```

Vertical budget checks out exactly: `150 + 24 + 390 + 24 + 285 + 24 + 212 = 1109`.

**Reading order is column-major within each row band**, which is how people actually walk
a poster. P3 sits at eye level in the right column because judges look right first when the
left column is occupied by another reader.

---

## 2. Visual system

### Palette

Inherited from `build_defense_brief.py`'s constants, with two deliberate changes noted
below. Print target is **CMYK**; the hexes below are the sRGB masters to convert from.

| Role | Hex | Use |
|---|---|---|
| `--ink-heading` | `#1B2A4A` | Panel headings, title, table header fill |
| `--ink-body` | `#3D3D3D` | Body copy |
| `--ink-muted` | `#6E6E6E` | Axis labels, captions, footnotes (4.5:1 on panel fill) |
| `--paper` | `#FDFCFA` | Poster background |
| `--panel` | `#F2F1ED` | Panel fill — the brief's warm grey |
| `--emph` | `#1F6FB2` | **Emphasis**: XGBoost marks, the accent rule |
| `--deemph` | `#8A887F` | Baseline/context marks, gridlines |
| `--critical` | `#B02A2A` | Blocked / prevention marks, limitation flags |

**Two changes from the brief, both on purpose:**

1. **Green is removed entirely.** The brief's `GOOD #0CA30C` against `CRITICAL #B02A2A`
   measures **deuteranopic ΔE 2.1** — indistinguishable to ~6% of men, which at a defense
   is a coin-flip on whether a judge can read the poster's core allowed/blocked contrast.
   The blue↔red axis replaces it and passes every gate (deutan ΔE 21.4, tritan 30.1,
   normal-vision 28.1, both ≥3:1 on `--panel`).
2. **`--deemph` is `#8A887F`, not a lighter grey.** `#9A988F` measured 2.56:1 on
   `--panel` — under the 3:1 floor. `#8A887F` clears it while still receding behind
   `--emph`.

Validation run (`dataviz/scripts/validate_palette.js`, `--mode light --surface #F2F1ED`):

```
#1F6FB2, #8A887F, #B02A2A
  [PASS] Lightness band      all 3 inside L 0.43–0.77
  [FAIL] Chroma floor        #8A887F reads gray            ← intended, see below
  [PASS] CVD separation      worst #B02A2A↔#8A887F ΔE 13.5
  [PASS] Normal-vision floor worst #8A887F↔#1F6FB2 ΔE 17.1
  [PASS] Contrast vs surface all 3 ≥ 3:1
```

The one FAIL is a **scope mismatch, not a defect**: the chroma floor exists so two
*categorical* slots never both read as grey. This poster's charts use the **emphasis**
form — one hue plus a deliberately achromatic grey — where the grey being colorless *is*
the encoding. Don't "fix" it by saturating `--deemph`; that destroys the form.

### Type

System sans throughout (`Inter`, or `Source Sans 3`; fall back to `Calibri` to match the
brief). No serif, no display face. Tabular figures in tables and axis ticks only.

| Role | Size | Weight |
|---|---|---|
| Poster title | 96 pt | Bold |
| Subtitle | 44 pt | Regular |
| Authors / affiliation | 32 pt | Regular |
| KPI value | 90 pt | Bold |
| KPI label | 24 pt | Regular, `--ink-muted` |
| Panel heading | 40 pt | Bold, `--ink-heading` |
| Panel subhead | 30 pt | Semibold |
| Body | 26 pt | Regular |
| Table body | 24 pt | Regular |
| Axis / caption | 22 pt | Regular, `--ink-muted` |
| Footnotes / refs | 18 pt | Regular |

**26 pt body is a floor, not a target** — it is what makes the poster readable at 2 m.
The corollary is a hard constraint: **total body copy across all eight panels must stay
under ~650 words.** If a panel needs more, it becomes a figure or it gets cut. Every
panel below is written to that budget.

### Panel chrome

- Panel fill `--panel`, corner radius 6 mm, no drop shadow (shadows print as mud).
- 0.5 mm `--deemph` hairline rule under each panel heading, full panel width.
- 16 mm internal padding.
- A 4 mm `--emph` bar on the **left edge of P3 only** — the one visual cue marking the
  results panel as the poster's centre of gravity.

### Print marks

Scaled up from screen specs, since 2 px means nothing at A0:

| Mark | Size |
|---|---|
| Gridline (hairline) | 0.4 mm `--deemph` at 35% |
| Axis / baseline | 0.8 mm `--deemph` |
| Scatter marker | 11 mm diameter, 1 mm `--panel` ring |
| Bar data-end radius | 1.5 mm |
| Gap between adjacent fills | 2 mm |

No hover layer, no dark mode — this is print. The skill's interaction layer is
**not applicable**; the substitute is that **every mark is direct-labeled and the full
table is present**, which is the documented relief for a static medium.

Texture fill (45° lines, tone-on-tone) is **available but off by default**. Turn it on for
the `--critical` marks only if the print proof shows weak red/blue separation.

---

## 3. Title band

```
        Real-Time Fraud Detection and Automated Prevention
                for Mobile Money in Africa
     ────────────────────────────────────────────────────────
     A four-signal ensemble — gradient boosting, unsupervised
     anomaly detection, and an auditable rule engine — scoring
     live transaction traffic and freezing compromised accounts
                    without rescanning history

     Group 13   ·   [Department]   ·   [Institution]   ·   2026
```

Title centered, `--ink-heading`. Subtitle `--ink-body`. A 1 mm `--emph` rule between
title and subtitle.

### KPI strip — 4 tiles, full width

Four tiles at `761 ÷ 4 = 190 mm` each, separated by 0.5 mm `--deemph` vertical rules.
Value in `--emph` at 90 pt, label beneath in `--ink-muted` at 24 pt.

| Value | Label |
|---|---|
| **0.858** | PR-AUC, best of six models<br>(held-out future transactions) |
| **86.2%** | of fraud caught<br>(576 of 668) |
| **0** | false blocks<br>(11 of 11 hard blocks were real fraud) |
| **O(1)** | scoring cost per transaction<br>(independent of history size) |

> **Every one of these four is reproducible from the repo** — the first two from
> `outputs/model_comparison.csv`, the third from the severe-rule audit, the fourth from
> the profile-store design. Do **not** put the older "17 flagged / 0 false positives"
> figure on the poster: it was measured with models trained on the same 2,000 rows they
> were scored on, and does not reproduce against the currently committed artifacts
> (which yield 64 false positives on that file). It is the single most attackable number
> in the project. See §10.

---

## 4. P1 — The Problem

**Heading:** `The threat is telco-specific, and mostly invisible to card-fraud tools`

Two short paragraphs (≈70 words total), then the table. The table does the work.

| Attack | How it runs | Signal that exposes it |
|---|---|---|
| **SIM swap** | Agent-assisted SIM replacement, wallet re-paired to attacker's handset, drained within minutes | IMEI change + immediate large cash-out |
| **Structuring** | Many sub-threshold transfers evading the single-transaction cap | Windowed **sum**, not amount |
| **Mule fan-in** | Many wallets → one collector → agent cash-out | Distinct-senders / incoming ratio |
| **Rapid fan-out** | One compromised wallet sprays funds across recruited mules | New counterparty during a velocity burst |
| **Dormant takeover** | Long-quiet wallet suddenly emptied | Silence gap + large amount |

**Closing line, set in `--emph`:** *Four of these five are defined by behaviour over
time, not by any property of the transaction itself.* — this is the sentence that
motivates the entire profile architecture in P2.

---

## 5. P2 — The Pipeline

**Heading:** `One feature implementation, trained and served`

Diagram, vertical flow, ~200 mm tall:

```
      feeder.py  ──inserts──▶  transactions (scored_at IS NULL)
                                        │
                                        ▼
                        ┌───────────────────────────────┐
                        │  compute_batch_features()      │
                        │  30 features, computed CAUSALLY│
                        └───────────────────────────────┘
                          ▲                          │
              ┌───────────┴──────────┐               ▼
              │ user_profiles         │        ENSEMBLE SCORING
              │ Welford: count/mean/m2│               │
              │ ONE row per user      │◀──update──────┘
              └──────────────────────┘
```

Then three short claims, each one line, each with the number that proves it:

- **The same code trains and serves.** `build_feature_table()` replays history through
  the *live* incremental function. There is no second implementation to drift.
- **No history rescan, ever.** One indexed PK lookup per user in the batch, one bounded
  range scan for the 24 h window. Cost is flat in total history.
- **14 behavioural features, verified identical** to 6 decimal places between the
  offline and online paths.

Below the diagram, a 3-row micro-table of feature families: transaction-level (11),
behavioural (14), device/SIM (2). Set counts in `--emph`.

---

## 6. P3 — Results *(centre of gravity)*

**Heading:** `XGBoost is the only model that is both precise and complete`

That heading is the claim to defend, and it is deliberately **not** "XGBoost has the
best PR-AUC." The top three models sit within 0.016 PR-AUC of each other — a judge will
notice, and a poster that leads with the ranking invites *"that's inside noise."* The
defensible claim is about the **shape** of the failures, which the figure makes
unarguable.

### Figure 1 — Precision–recall position, six models

The only chart on the poster. **Emphasis scatter**, `237 × 180 mm`.

- x = recall (0 → 1), y = precision (0 → 1), both axes full range so the empty
  top-right corner is visible.
- 6 points, 11 mm, **direct-labeled** with the model name. No legend.
- XGBoost in `--emph`; the other five in `--deemph`.
- Dotted iso-F1 contours at 0.4 / 0.6 / 0.8 in `--deemph` at 30%, labeled at the right
  edge.
- Annotate two failure directions in `--ink-muted`, 22 pt:
  - near Random Forest → *"precise but misses 363 of 668"*
  - near Logistic Regression → *"complete but 765 false alarms"*

| Model | Recall | Precision |
|---|---|---|
| **XGBoost** | 0.862 | 0.644 |
| Logistic Regression | 0.949 | 0.453 |
| Random Forest | 0.457 | 0.924 |
| Isolation Forest | 0.430 | 0.260 |
| Rule Engine | 0.157 | 0.963 |
| Local Outlier Factor | 0.599 | 0.054 |

The visual argument: **XGBoost is alone in the upper-right region.** Every alternative
is pinned to one axis.

### Table 1 — Six models, one held-out split

Straight from `outputs/model_comparison.csv`. Header row filled `--ink-heading`, white
text. XGBoost row filled `--emph` at 12% tint. Tabular figures.

| Model | PR-AUC | ROC-AUC | Precision | Recall | FP | FN |
|---|---|---|---|---|---|---|
| **XGBoost** | **0.858** | 0.987 | 0.644 | 0.862 | 318 | 92 |
| Logistic Regression | 0.843 | 0.987 | 0.453 | 0.949 | 765 | 34 |
| Random Forest | 0.842 | 0.985 | 0.924 | 0.457 | 25 | 363 |
| Isolation Forest | 0.398 | 0.814 | 0.260 | 0.430 | 817 | 381 |
| Rule Engine | 0.312 | 0.701 | 0.963 | 0.157 | 4 | 563 |
| Local Outlier Factor | 0.056 | 0.491 | 0.054 | 0.599 | 7043 | 268 |

**Caption, 22 pt:** *12,000 held-out transactions, 668 fraud. Time-based split — trained
on the past, tested on the future. PR-AUC leads because ROC-AUC flatters heavily
imbalanced classes.*

Keep the LOF row in. Deleting a bad result reads as concealment; keeping it and
explaining it in P7 reads as command of the material.

---

## 7. P4 — Three Complementary Signals

**Heading:** `Each model covers a blind spot the others cannot`

The matrix is the panel. No prose beyond one opening line.

| | XGBoost | Isolation Forest | Rules |
|---|---|---|---|
| Known, labelled pattern | ● | ◐ | only if written |
| **Pattern never seen or labelled** | ○ | ● | ○ |
| **Day-one deploy, zero labels** | ○ | ● | ● |
| First-ever transaction, no history | ◐ | ◐ | ● |
| Ledger invariant violated | ◐ | ◐ | ● |
| **Explains itself to a regulator** | ○ | ○ | ● |
| Same-day response to new fraud | ○ | ◐ | ● |

`● covers · ◐ partial · ○ blind` — **glyph plus the legend, never colour alone.** Fill
`●` in `--emph`, `○` in `--deemph`.

**Closing line in `--emph`:** *Every row has a blind spot. No column is blind on every
row.*

One supporting number, boxed: judged **alone** at its own operating point on the seed
dataset, Isolation Forest found **15 of 17 frauds with 5 false positives — having never
seen a label.** That is the day-one argument in a single figure.

---

## 8. P5 — Ensemble & Prevention

**Heading:** `From probability to a frozen account`

The blend, set large and centered as the panel's hero element:

```
   fraud_probability = 0.55·XGB + 0.15·IsoF + 0.15·LOF + 0.15·Rules

   flagged  ⟶  p ≥ 0.50
   BLOCKED  ⟶  p ≥ 0.80   OR   a severe rule fires alone
```

`BLOCKED` in `--critical`, `flagged` in `--emph`.

**Then the point most posters miss — why the `OR` exists.** Two lines:

> XGBoost is capped at 0.55 weight, so a transaction it is *100% certain* about scores
> 0.55 — flagged, but below the block threshold. A brand-new account with no behavioural
> history, where both anomaly detectors have nothing to compare against, is blockable
> **only** through the rule path.

Then the prevention loop, as a 4-step horizontal chain with arrows:

```
severe rule fires  →  transaction BLOCKED  →  kyc_status = 'suspended'
                                                        │
                          feeder refuses that account ◀─┘
                                as a sender
```

**Closing line:** *Detection writes a row. Prevention stops the next transaction.* Note
honestly, at 22 pt: in production this check belongs at authorization time, before the
transaction commits.

---

## 9. P6 — Live System

**Heading:** `Running system, not a notebook`

Top ~180 mm: **screenshot of the React dashboard**, alerts page, at least one blocked
transaction with its `block_reason` visible. Crop to the panel, 1 mm `--deemph` border,
no device mockup frame.

Callout arrow in `--critical` pointing at one `block_reason` string, e.g.:

> `device changed this txn + GHS 15,676.00 cash-out (SIM-swap pattern)`

**Caption:** *Every block ships a plain-language reason. This is what a customer dispute
or a Bank of Ghana enquiry gets answered with — not a model score.*

Bottom ~85 mm, the stack as a strip of five labeled blocks:

`Postgres` → `feeder.py` → `monitor.py` → `FastAPI` → `React`

with one line under it: *4 s dashboard poll; scoring latency measured at the engine, not
from row age.*

---

## 10. P7 — Limitations & Future Work

**Heading:** `What this system does not yet do`

Spans two columns (498 mm) — deliberately given real estate rather than buried in 18 pt
at the bottom. **This panel is a defensive asset.** Every item is something a judge could
find; each is stated with the number and the fix, which converts an attack into evidence
of command.

Two columns of content inside the panel:

| Limitation | Fix |
|---|---|
| **`txn_type_TRANSFER` carries 58.6% of XGBoost's gain.** The generator emits fraud only as TRANSFER/CASH_OUT, so the model learned a data artifact, not behaviour. All 14 behavioural features together contribute ~2%. | Stratify injected fraud across all five transaction types; drop or regularize the type dummies; retrain. |
| **LOF holds 15% ensemble weight at ROC-AUC 0.491** — below chance. Its k-NN distance metric is meaningless across mixed-scale features (cedis vs counts vs flags). | Drop it. Reweight XGB 0.60 / IsoF 0.20 / Rules 0.20. |
| **Ensemble weights are hand-set, never validated.** | Fit a stacked meta-learner on held-out data, or grid-search the weights against a cost-weighted objective. |
| **Fraud base rate is 5.6% synthetic vs ~0.1–1% real.** Precision would fall at a realistic base rate. | Re-evaluate at production prevalence; report cost-weighted precision. |
| **Validated on one synthetic operator, one currency (GHS).** | Percentile-learned thresholds are designed for this, but portability is argued, not yet demonstrated. |

**Closing line in `--ink-body`, not hidden:** *The architecture is sound and the rule
path is verified clean; the supervised model's training distribution is the open problem.*

That sentence is the poster's credibility. It says: we know exactly where the weakness is.

---

## 11. P8 — Conclusion

**Heading:** `Contribution`

Four numbered claims, 26 pt, nothing else. No "future work" (it's in P7), no thank-yous.

1. **A four-signal ensemble** whose components have measurably disjoint failure modes —
   supervised recall, unsupervised novelty coverage, and auditable invariants.
2. **Detection through to prevention**, closed and demonstrated: a hard block suspends
   the account and the transaction source stops originating from it.
3. **O(1) per-transaction scoring** via incremental Welford profiles, verified feature-identical
   to full offline recomputation — the property that makes this deployable at telco volume.
4. **Percentile-learned rule thresholds**, so the same engine ports across operators and
   currencies without re-tuning magic constants.

Footer strip, 18 pt `--ink-muted`, full panel width: repo URL / QR code, and
`README.md` + `DOCUMENTATION.md` as the pointers for detail.

---

## 12. Build notes

- **Author in HTML/CSS at `1 mm = 1 px` (841 × 1189 px), print to PDF at scale 1000%**,
  or author directly in Illustrator/Affinity/Inkscape. LaTeX `tikzposter`/`beamerposter`
  is fine but fights the panel-span layout in §1.
- **Figure 1 must be vector** (SVG), never a raster export — 11 mm markers and 22 pt
  labels will fringe visibly at A0 otherwise.
- The dashboard screenshot in P6 is the one exception; capture it at **≥ 3× device pixel
  ratio** and place it at no more than 1/3 of its native pixel dimensions.
- **Convert to CMYK before sending to print and proof `--emph` and `--critical`.**
  `#1F6FB2` and `#B02A2A` both sit inside sRGB but shift on uncoated stock; if the proof
  weakens their separation, enable the texture channel (§2) on `--critical`.
- Proof test: print one panel at A4 100% and read it at arm's length. If any body text is
  uncomfortable, the poster fails at 2 m.

### Convention to preserve

**Every number on this poster must be reproducible from the repo, and the panel that
prints it must name where it comes from.** Where a number is contested or stale, it goes
in P7 with its correction — never silently dropped, and never printed as though it still
holds.
