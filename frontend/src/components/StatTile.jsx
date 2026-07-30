export function StatTile({ label, value, tone = "neutral", sublabel, icon }) {
  return (
    <div className="stat-card">
      <div className="stat-card-top">
        <span className="stat-card-label">{label}</span>
        {icon && <span className={`stat-card-icon stat-card-icon-${tone}`} aria-hidden="true">{icon}</span>}
      </div>
      <div className="stat-card-value">{value}</div>
      {sublabel && <div className={`stat-card-sublabel stat-card-sublabel-${tone}`}>{sublabel}</div>}
    </div>
  );
}
