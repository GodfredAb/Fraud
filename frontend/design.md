# Frontend Design

Documents the frontend **as it currently exists** — architecture, design system,
component inventory, and data flow. Written as a reference, not a proposal.

Superseded a terminal/monospace, single-page dashboard with this app-shell (topbar +
sidebar), multi-page, light card-based design — a full visual pivot, not an iteration.

## 1. Stack

- **React 19** + **Vite 8** (`@vitejs/plugin-react`), plain JS (no TypeScript, despite
  `@types/react` being present — those are editor-hint-only).
- No router library, no state library, no UI kit, no CSS framework. Two hand-written
  stylesheets (`index.css` for tokens/reset, `App.css` for everything else), one
  polling hook, and a `useState` for the active page are the entire "framework."
- `oxlint` for linting (`npm run lint`).
- Talks to the FastAPI backend (`api/main.py`) over plain `fetch`, driven by
  `VITE_API_URL` (defaults to `http://localhost:8000`).

## 2. Architecture: poll-and-render, no client state management

There is no Redux/Zustand/Context store and no client-side cache. The entire app is one
pattern, repeated: **`usePolling` hook → prop drilling → dumb render components**,
wrapped in an `AppShell` that switches which page's content renders.

```
App.jsx
 ├─ usePolling(api.stats,            4000ms) → stats
 ├─ usePolling(api.alerts,           4000ms) → alerts
 ├─ usePolling(api.recentTransactions,4000ms) → recent
 ├─ usePolling(api.suspended,        4000ms) → suspended
 ├─ usePolling(api.fraudLocations,   4000ms) → fraudLocations
 ├─ useState(selectedTxnId)  ← detail-modal state
 └─ useState(page)           ← "dashboard" | "alerts" | "accounts" | "map" | "reports"
```

Every page's data comes from the SAME polling calls made once at the top of `App.jsx` -
switching pages doesn't trigger new fetches, it just changes which already-fetched data
renders. `usePolling` (`hooks/usePolling.js`) fires immediately, then every
`intervalMs`, and — deliberately — **keeps stale data on screen through a failed poll**
rather than blanking the UI, surfacing the failure via a separate `error` return value.

Every list/table component is a pure function of props: given `null` → loading state,
given `[]` → an explicit empty state, given rows → render. None of them fetch their own
data except `TransactionDetail` (see below).

### Why polling, not WebSockets/SSE

The backend (`api/main.py`) is a plain read-mostly REST API with no push channel. Given
the data changes at the pace of `monitor.py`'s scoring cycle (seconds, not
milliseconds), a 4s poll is simple, debuggable in plain `curl`, and needs no connection
lifecycle handling on either side. Documented here as a decision, not an oversight.

## 3. Pages (client-side only, no URL routing)

`page` is plain `useState` in `App.jsx`, not a router - there's no deep-linkable URL per
page, refreshing always lands back on "dashboard". `AppShell` renders the sidebar/topbar
chrome and calls back via `onNavigate(pageKey)`.

| Page | Content | Real or placeholder |
|---|---|---|
| `dashboard` (sidebar "Dashboard", topbar "Overview") | 4 stat cards, Fraud Alerts, Activity Feed, Suspended Accounts (top 5), Geo-Location Deltas | Real |
| `alerts` | Full Fraud Alerts table + Live Scoring Feed | Real |
| `accounts` | Full Suspended Accounts list | Real |
| `map` | — | **Placeholder** - no mapping library; honestly labeled, points at the Geo-Location Deltas table instead of faking a map |
| `reports` (topbar tab) | — | **Placeholder** |

The topbar's search input, notification/settings/help icons, avatar, and the sidebar's
"+ New Report"/Support/Logs are all **visually present but inert** (`disabled` or a
`title` explaining they're not wired up) — present because the target design calls for
them, not because they do anything. Don't remove the `title` attributes if you touch
these; they're the only signal to a user that clicking does nothing.

## 4. Data flow for the one interactive element: row click → detail modal

`AlertsTable`, `RecentActivity`, and `FraudLocations`' Review button all take an
`onSelect(txnId)` callback. `App.jsx` wires all three to a single `selectedTxnId`
state value, and renders one `<TransactionDetail txnId={selectedTxnId} onClose={...} />`
when it's non-null - regardless of which page is currently active (the modal isn't
page-scoped).

`TransactionDetail` is the only component that fetches its own data (`api.transaction`,
on mount / `txnId` change) rather than receiving it as a prop - deliberately: it's a
drill-down triggered by user action, not part of the steady-state poll loop.

Escape-to-close is wired via a `keydown` listener; click-outside-to-close via an
`onClick` on the overlay that a `stopPropagation()` on the inner panel prevents from
firing when the click originated inside.

## 5. Component inventory

| Component | Role | Own data fetch? |
|---|---|---|
| `App.jsx` | Layout, polling wiring, page + modal state | No |
| `AppShell.jsx` | Topbar + sidebar chrome, nav | No |
| `StatTile.jsx` | One stat-card (label/value/sublabel/tone/icon) | No |
| `AlertsTable.jsx` | Fraud Alerts table (ID/Timestamp/Type/Probability/Status), click → detail | No |
| `RecentActivity.jsx` | Live scoring feed table, click → detail | No |
| `SuspendedAccounts.jsx` | Suspended-accounts list | No |
| `FraudLocations.jsx` | Geo-Location Deltas: highest-fraud-probability subscribers, home vs. current location, Review → detail | No |
| `ActivityFeed.jsx` | System-action log, derived client-side from `alerts`+`suspended` (no separate audit-log endpoint) | No |
| `TransactionDetail.jsx` | Modal: full detail for one transaction | **Yes** |
| `ProbabilityPill.jsx` | Tinted rounded pill showing the raw probability (e.g. `0.85`), shared by both tables | No |

`ActivityFeed` is worth calling out: every line it shows is a REAL system action (a
block, a suspension) with a real timestamp, reconstructed from data already on screen
elsewhere. It deliberately does not fabricate analyst/human entries ("Analyst_04
reviewed...") since no such audit trail exists in the backend.

## 6. Design system

### Aesthetic: light, card-based, sans-serif

A conventional ops-dashboard look: white cards (`--surface-1`) on a light gray page
background (`--surface-0`), `border-radius: 10px`, a subtle shadow (`--shadow-sm`), a
blue brand accent (`--brand`), and tinted (not bracket-notation) status pills/labels.
System-UI sans-serif stack, no monospace-everywhere.

### Color tokens (`index.css`)

CSS custom properties, light values in `:root`, dark values under
`@media (prefers-color-scheme: dark)` — no manual theme toggle, it follows the OS.

| Token | Role |
|---|---|
| `--surface-0/1/2` | Page background / card background / secondary bg (search box, hover) |
| `--text-primary/secondary/muted` | Decreasing emphasis |
| `--border`, `--gridline` | `--border` for structural lines (card/table edges), `--gridline` for row separators |
| `--brand`, `--brand-tint`, `--brand-hover` | Primary blue accent — active nav, links, primary button, its own hover/tint steps |
| `--status-good/warning/serious/critical` + `-text`/`-tint` variants | Semantic status color; `-text` is a contrast-adjusted step for text on a tint background, `-tint` is the pill/badge fill |
| `--radius`, `--radius-sm` | 10px / 6px, used everywhere instead of one-off values |
| `--shadow-sm`, `--shadow-md` | Card elevation / modal elevation |

Status is never color-only: `ProbabilityPill` and `.status-label` always ship the
number or an icon+text label alongside the tint.

### Layout primitives

- **`.shell` / `.topbar` / `.sidebar` / `.shell-main`**: the app frame, built once in
  `AppShell.jsx` and never duplicated per-page.
- **`.panel`**: the one card/container type page content lives in — `.panel-header`
  (bottom border) + body.
- **`.dash-grid`** / **`.dash-side`**: the dashboard page's two-column layout (Fraud
  Alerts main + Activity Feed/Suspended Accounts stacked in a sidebar column),
  collapsing to one column under 960px.
- **`.stat-grid`** / **`.stat-card`**: `repeat(auto-fit, minmax(200px, 1fr))` cards,
  each independently bordered+shadowed (unlike the old shared-gridline trick).
- **`.data-table`**: the shared table look, used by every table on every page.
- **`.modal-overlay` / `.modal-panel`**: fixed-position overlay + centered panel, used
  only by `TransactionDetail`.

### Responsiveness

Single breakpoint at 960px (`.dash-grid` stacking). The sidebar does not collapse to a
drawer below that — this is still built for a desk-sized viewport, an ops/analyst tool
rather than a consumer-facing responsive surface.

## 7. Conventions worth preserving if you extend this

- **New list component → three-state render** (`null`/`[]`/rows), same as every
  existing one — `"Loading…"` in `.muted` text is the established pattern.
- **New polled data → add one `usePolling` call in `App.jsx`**, pass the result down as
  a named prop, available to every page regardless of which one is active.
- **New status/severity indicator → a tinted `.status-label` or pill**, using the
  `-text`/`-tint` token pairs, never color alone.
- **New API call → add one line to `api.js`'s `api` object**, wrapping the shared
  `get()` helper.
- **New non-functional chrome (mirroring a design mock) → keep it honestly inert**:
  `disabled` or a `title` explaining it's not wired up, never a silent no-op that looks
  like it should do something.
