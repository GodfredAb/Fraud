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

export function TransactionDetail({ txnId, onClose }) {
  const [txn, setTxn] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setTxn(null);
    setError(null);
    api.transaction(txnId).then(setTxn).catch((e) => setError(String(e)));
  }, [txnId]);

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const wasFlaggedOrBlocked = txn && (txn.flagged || txn.blocked);
  const reason = txn?.block_reason || (txn?.flagged ? "ensemble_probability_threshold (flagged, below block threshold)" : null);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>TRANSACTION #{txnId}</h2>
          <button className="modal-close" onClick={onClose} aria-label="Close">[x]</button>
        </div>

        {error && <p className="banner banner-error">{error}</p>}
        {!txn && !error && <p className="muted" style={{ padding: "14px" }}>Loading…</p>}

        {txn && (
          <div className="modal-body">
            <Row label="Type">{txn.txn_type}</Row>
            <Row label="Amount">{money(txn.amount)}</Row>
            <Row label="Occurred">{txn.txn_timestamp ? new Date(txn.txn_timestamp).toLocaleString() : `step ${txn.txn_step}`}</Row>

            <div className="detail-section">Sender</div>
            <Row label="User">{txn.sender_name || txn.sender_user_id} ({txn.sender_user_id})</Row>
            <Row label="MSISDN">{txn.sender_msisdn || "—"}</Row>
            <Row label="IMEI">{txn.sender_imei || "—"}</Row>
            <Row label="Balance">{money(txn.sender_balance_old)} → {money(txn.sender_balance_new)}</Row>

            <div className="detail-section">Receiver</div>
            <Row label="User">{txn.receiver_name || txn.receiver_user_id} ({txn.receiver_user_id})</Row>
            <Row label="MSISDN">{txn.receiver_msisdn || "—"}</Row>
            <Row label="IMEI">{txn.receiver_imei || "—"}</Row>
            <Row label="Balance">{money(txn.receiver_balance_old)} → {money(txn.receiver_balance_new)}</Row>

            <div className="detail-section">Scoring</div>
            <Row label="Fraud probability">{(txn.fraud_probability * 100).toFixed(1)}%</Row>
            <Row label="Status">
              {txn.blocked ? "BLOCKED" : txn.flagged ? "FLAGGED" : "clear"}
            </Row>
            {wasFlaggedOrBlocked && (
              <>
                <Row label={txn.blocked ? "Blocked at" : "Flagged at"}>
                  {txn.scored_at ? new Date(txn.scored_at).toLocaleString() : "—"} ({relativeTime(txn.scored_at)})
                </Row>
                <Row label="Reason">{reason}</Row>
              </>
            )}
            <Row label="Scored at">{txn.scored_at ? new Date(txn.scored_at).toLocaleString() : "not yet scored"}</Row>
            <Row label="Model version">{txn.model_version || "—"}</Row>
          </div>
        )}
      </div>
    </div>
  );
}
