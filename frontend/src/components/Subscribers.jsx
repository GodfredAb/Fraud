import { useEffect, useState } from "react";
import { api } from "../api";

export function Subscribers({ onSelectSubscriber }) {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const handle = setTimeout(() => {
      api.subscribers(q, 40)
        .then((r) => !cancelled && setRows(r))
        .catch((e) => !cancelled && setError(String(e)));
    }, q ? 250 : 0);
    return () => {
      cancelled = true;
      clearTimeout(handle);
    };
  }, [q]);

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>Subscribers</h2>
        <span className="muted">{rows ? `${rows.length} shown` : "loading…"}</span>
      </div>

      <div className="subscriber-search">
        <input
          type="text"
          placeholder="Search by name, subscriber ID, or MSISDN…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          autoFocus
        />
      </div>

      {error && <p className="banner banner-error">{error}</p>}
      {!rows && !error && <p className="muted" style={{ padding: "14px" }}>Loading…</p>}

      {rows && rows.length === 0 && <p className="muted" style={{ padding: "14px" }}>No matching subscribers.</p>}

      {rows && rows.length > 0 && (
        <table className="data-table">
          <thead>
            <tr>
              <th>Subscriber</th>
              <th>MSISDN</th>
              <th>KYC status</th>
              <th>Home region</th>
              <th>Registered</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((u) => (
              <tr key={u.user_id} className="clickable-row" onClick={() => onSelectSubscriber(u.user_id)}>
                <td>{u.full_name} <span className="muted">({u.user_id})</span></td>
                <td>{u.msisdn}</td>
                <td><span className={`kyc-badge kyc-${u.kyc_status}`}>{u.kyc_status}</span></td>
                <td>{u.home_city ? `${u.home_city}, ${u.home_region}` : "—"}</td>
                <td>{u.registration_date ? new Date(u.registration_date).toLocaleDateString() : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
