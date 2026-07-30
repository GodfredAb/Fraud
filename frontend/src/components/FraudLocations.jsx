import { relativeTime } from "../format";

// CRITICAL above this distance from home. NOT a real-world commuting-
// distance number - current location is one recent ping, home is the
// AVERAGE of all pings, and database/seed_generator.py jitters each ping
// only +-0.02deg (~2.2km) around a user's home range, so distances between
// current and home rarely exceed ~3km even for genuinely flagged
// subscribers (observed max across all flagged users: 3.2km). 2.5km is
// this population's own ~90th percentile - "meaningfully far for this
// dataset's actual scale", the same population-relative philosophy
// ml/rules.py uses for its percentile-based cutoffs, not an arbitrary
// absolute distance.
const CRITICAL_DISTANCE_KM = 2.5;

export function FraudLocations({ rows, onSelect }) {
  if (!rows) {
    return <p className="muted">Loading…</p>;
  }
  if (rows.length === 0) {
    return <p className="muted">No flagged subscribers yet.</p>;
  }

  return (
    <div className="table-scroll">
      <table className="data-table">
        <thead>
          <tr>
            <th>Subscriber ID</th>
            <th>Location Delta</th>
            <th>Distance</th>
            <th>Last Seen</th>
            <th>Velocity Score</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const critical = (r.distance_from_home_km ?? 0) > CRITICAL_DISTANCE_KM;
            return (
              <tr key={r.user_id}>
                <td className="mono">{r.user_id}</td>
                <td>
                  <span title={r.home_address?.formatted}>{r.home_address?.city ?? "—"}</span>
                  {" → "}
                  <span title={r.current_address?.formatted}>{r.current_address?.city ?? "—"}</span>
                </td>
                <td className="num mono">
                  {r.distance_from_home_km != null ? `${r.distance_from_home_km} km` : "—"}
                </td>
                <td className="muted">{relativeTime(r.current_location_at)}</td>
                <td>
                  <span className={`status-label status-label-${critical ? "critical" : "good"}`}>
                    {critical ? "CRITICAL" : "NORMAL"}
                  </span>
                </td>
                <td>
                  <button className="review-button" onClick={() => onSelect?.(r.top_txn_id)}>
                    Review
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
