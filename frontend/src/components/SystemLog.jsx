import { useEffect, useState } from "react";
import { api } from "../api";
import { money, relativeTime } from "../format";

export function SystemLog({ onSelect }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.systemLog(75).then(setRows).catch((e) => setError(String(e)));
  }, []);

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>System Log</h2>
        <span className="muted">most recently scored, newest first</span>
      </div>

      {error && <p className="banner banner-error">{error}</p>}
      {!rows && !error && <p className="muted" style={{ padding: "14px" }}>Loading…</p>}
      {rows && rows.length === 0 && <p className="muted" style={{ padding: "14px" }}>No scored transactions yet.</p>}

      {rows && rows.length > 0 && (
        <table className="data-table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Txn</th>
              <th>Amount</th>
              <th>Route</th>
              <th>Decision</th>
              <th>Model</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.txn_id} className="clickable-row" onClick={() => onSelect?.(r.txn_id)}>
                <td>{relativeTime(r.scored_at)}</td>
                <td>#{r.txn_id}</td>
                <td>{money(r.amount)}</td>
                <td>{r.sender_user_id} → {r.receiver_user_id}</td>
                <td>
                  {r.blocked ? "BLOCKED + SUSPENDED" : r.flagged ? "FLAGGED" : r.auto_approved ? "auto-approved" : "pending"}
                </td>
                <td className="muted">{r.model_version || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
