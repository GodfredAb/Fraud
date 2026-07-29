import { relativeTime } from "../format";

function coord(lat, lon) {
  if (lat == null || lon == null) return "—";
  return `${Number(lat).toFixed(4)}, ${Number(lon).toFixed(4)}`;
}

export function FraudLocations({ rows }) {
  if (!rows) {
    return <p className="muted">Loading…</p>;
  }
  if (rows.length === 0) {
    return <p className="muted">No flagged subscribers yet.</p>;
  }

  return (
    <div className="table-scroll">
      <table className="data-table compact">
        <thead>
          <tr>
            <th>Subscriber</th>
            <th>Fraud prob.</th>
            <th>Current location</th>
            <th>Home location</th>
            <th className="num">Distance</th>
            <th>Last flagged</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.user_id}>
              <td>
                {r.full_name} <span className="muted">({r.user_id})</span>
              </td>
              <td className="mono">{(r.max_fraud_probability * 100).toFixed(0)}%</td>
              <td className="mono" title={r.current_location_at ? new Date(r.current_location_at).toLocaleString() : ""}>
                {coord(r.current_latitude, r.current_longitude)}
              </td>
              <td className="mono">{coord(r.avg_latitude, r.avg_longitude)}</td>
              <td className="num mono">
                {r.distance_from_home_km != null ? `${r.distance_from_home_km} km` : "—"}
              </td>
              <td className="muted">{relativeTime(r.last_flagged_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
