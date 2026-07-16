export function StatTile({ label, value, tone = "neutral", sublabel }) {
  return (
    <div className={`stat-tile stat-tile-${tone}`}>
      <div className="stat-tile-label">{label}</div>
      <div className="stat-tile-value">{value}</div>
      {sublabel && <div className="stat-tile-sublabel">{sublabel}</div>}
    </div>
  );
}
