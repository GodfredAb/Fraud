/**
 * Fraud probability rendered as a status pill - color is never the only
 * signal (warning/serious dip below 3:1 contrast on a light surface by
 * design in the palette), so the numeric value and a text label always
 * ship alongside the color.
 */
export function ProbabilityPill({ value, blockThreshold, alertThreshold }) {
  const pct = Math.round(value * 100);
  let tone = "good";
  let label = "low";
  if (value >= blockThreshold) {
    tone = "critical";
    label = "blocked";
  } else if (value >= alertThreshold) {
    tone = "warning";
    label = "flagged";
  }

  return (
    <span className={`pill pill-${tone}`} title={`fraud_probability = ${value.toFixed(3)}`}>
      <span className="pill-dot" />
      {pct}% <span className="pill-label">{label}</span>
    </span>
  );
}
