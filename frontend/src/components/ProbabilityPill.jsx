/**
 * Fraud probability rendered as a tinted pill - color is never the only
 * signal (see the dataviz skill's status-palette note on light-surface
 * contrast), so the numeric value always ships alongside the color, and
 * the tint (not just the number) carries the severity at a glance.
 */
export function ProbabilityPill({ value, blockThreshold, alertThreshold }) {
  const pct = Math.round(value * 100);
  let tone = "good";
  if (value >= blockThreshold) {
    tone = "critical";
  } else if (value >= alertThreshold) {
    tone = "warning";
  }

  return (
    <span className={`prob-pill prob-pill-${tone}`} title={`fraud_probability = ${value.toFixed(3)}`}>
      {(value).toFixed(2)}
    </span>
  );
}
