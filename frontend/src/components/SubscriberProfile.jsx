import { useEffect, useState } from "react";
import { api } from "../api";
import { relativeTime, money } from "../format";

function Row({ label, children }) {
  return (
    <div className="detail-row">
      <div className="detail-label">{label}</div>
      <div className="detail-value">{children}</div>
    </div>
  );
}

export function SubscriberProfile({ userId, onClose, onSelectTxn }) {
  const [user, setUser] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setUser(null);
    setError(null);
    api.subscriberProfile(userId).then(setUser).catch((e) => setError(String(e)));
  }, [userId]);

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>SUBSCRIBER {userId}</h2>
          <button className="modal-close" onClick={onClose} aria-label="Close">[x]</button>
        </div>

        {error && <p className="banner banner-error">{error}</p>}
        {!user && !error && <p className="muted" style={{ padding: "14px" }}>Loading…</p>}

        {user && (
          <div className="modal-body">
            <div className="detail-section">Identity</div>
            <Row label="Name">{user.full_name}</Row>
            <Row label="MSISDN">{user.msisdn}</Row>
            <Row label="National ID">{user.national_id || "—"}</Row>
            <Row label="Gender / DOB">{user.gender || "—"} · {user.date_of_birth || "—"}</Row>
            <Row label="KYC status">
              <span className={`kyc-badge kyc-${user.kyc_status}`}>{user.kyc_status}</span>
            </Row>
            <Row label="Registered">
              {user.registration_date ? new Date(user.registration_date).toLocaleDateString() : "—"}
            </Row>

            <div className="detail-section">Device</div>
            <Row label="Current IMEI">{user.device?.imei || user.sender_last_imei || "—"}</Row>
            <Row label="Model">{user.device ? `${user.device.manufacturer} ${user.device.model}` : "—"}</Row>

            <div className="detail-section">Location</div>
            <Row label="Home">{user.home_address?.formatted || "unknown"}</Row>
            <Row label="Current">{user.current_address?.formatted || "unknown"}</Row>
            <Row label="Last seen">
              {user.current_location_at ? relativeTime(user.current_location_at) : "—"}
            </Row>

            <div className="detail-section">Behavioral baseline (learned from history)</div>
            <Row label="Transactions sent">{user.sender_txn_count?.toLocaleString() ?? 0}</Row>
            <Row label="Avg. amount sent">{user.sender_amount_mean != null ? money(user.sender_amount_mean) : "—"}</Row>
            <Row label="Largest sent">{user.sender_amount_max != null ? money(user.sender_amount_max) : "—"}</Row>
            <Row label="Distinct recipients">{user.sender_distinct_receivers?.toLocaleString() ?? 0}</Row>
            <Row label="Incoming transactions">{user.receiver_incoming_count?.toLocaleString() ?? 0}</Row>
            <Row label="Distinct senders">{user.receiver_distinct_senders?.toLocaleString() ?? 0}</Row>

            <div className="detail-section">Recent activity</div>
            {user.recent_transactions?.length ? (
              <table className="mini-table">
                <thead>
                  <tr>
                    <th>Txn</th>
                    <th>Type</th>
                    <th>Amount</th>
                    <th>Direction</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {user.recent_transactions.map((t) => (
                    <tr key={t.txn_id} className="clickable-row" onClick={() => onSelectTxn?.(t.txn_id)}>
                      <td>#{t.txn_id}</td>
                      <td>{t.txn_type}</td>
                      <td>{money(t.amount)}</td>
                      <td>{t.sender_user_id === userId ? "sent" : "received"}</td>
                      <td>
                        {t.blocked ? "BLOCKED" : t.flagged ? "FLAGGED" : t.auto_approved ? "approved" : "pending"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="muted">No transaction history.</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
