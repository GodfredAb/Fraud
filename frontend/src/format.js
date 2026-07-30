export function relativeTime(iso) {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  const now = Date.now();
  const diffSec = Math.max(0, Math.floor((now - then) / 1000));
  if (diffSec < 5) return "just now";
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  return new Date(iso).toLocaleDateString();
}

export function money(amount) {
  return new Intl.NumberFormat(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(amount);
}

/** Compact currency for stat tiles: "GHS 32.7k" instead of "GHS 32,736.65". */
export function shortMoney(amount) {
  if (amount == null) return "—";
  const abs = Math.abs(amount);
  if (abs >= 1_000_000) return `GHS ${(amount / 1_000_000).toFixed(1)}m`;
  if (abs >= 1_000) return `GHS ${(amount / 1_000).toFixed(1)}k`;
  return `GHS ${amount.toFixed(0)}`;
}

export function ms(value) {
  if (value == null) return "—";
  return value >= 1000 ? `${(value / 1000).toFixed(2)}s` : `${Math.round(value)}ms`;
}

/**
 * Maps a block_reason string (ml/ensemble.py's terse, technical explanation
 * text - see _RULE_PHRASES) to a short human category for the Fraud Alerts
 * table's "Type" column. Keyword-matched against the real reason text
 * rather than a separate stored field, since the rule engine's fired-rule
 * names aren't persisted on the transaction row, only the composed
 * explanation is - see api/main.py's docstring on why the API stays thin
 * rather than growing new derived columns for this.
 */
const REASON_TYPES = [
  [/SIM-swap/i, "Account Takeover"],
  [/structuring/i, "Structuring"],
  [/reactivation/i, "Dormant Reactivation"],
  [/fan-out/i, "Fan-Out"],
  [/mule fan-in/i, "Mule Fan-In"],
  [/velocity burst/i, "Velocity Surge"],
  [/night cash-out/i, "Night Cash-Out"],
  [/insufficient funds/i, "Insufficient Funds"],
  [/drained/i, "Account Drained"],
  [/ledger mismatch/i, "Ledger Mismatch"],
  [/P95 cutoff/i, "Amount Anomaly"],
  [/sigma vs self-avg/i, "Amount Anomaly"],
];
export function classifyReason(blockReason) {
  if (!blockReason) return "—";
  for (const [pattern, label] of REASON_TYPES) {
    if (pattern.test(blockReason)) return label;
  }
  return "ML Anomaly Score";
}
