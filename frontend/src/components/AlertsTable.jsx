import { ProbabilityPill } from "./ProbabilityPill";
import { relativeTime, money } from "../format";

export function AlertsTable({ alerts, blockThreshold, alertThreshold, onSelect }) {
  if (!alerts) {
    return <p className="muted">Loading alerts…</p>;
  }
  if (alerts.length === 0) {
    return <p className="muted">No alerts yet - waiting for the monitor to score traffic.</p>;
  }

  return (
    <div className="table-scroll">
      <table className="data-table">
        <thead>
          <tr>
            <th>When</th>
            <th>Txn</th>
            <th>Sender → Receiver</th>
            <th>Type</th>
            <th className="num">Amount</th>
            <th>Fraud probability</th>
            <th>Status</th>
            <th>Reason</th>
          </tr>
        </thead>
        <tbody>
          {alerts.map((a) => (
            <tr key={a.alert_id} className="clickable-row" onClick={() => onSelect?.(a.txn_id)}>
              <td className="muted">{relativeTime(a.alert_created_at)}</td>
              <td className="mono">#{a.txn_id}</td>
              <td>
                <span title={a.sender_msisdn}>{a.sender_name || a.sender_user_id}</span>
                {" → "}
                <span title={a.receiver_msisdn}>{a.receiver_name || a.receiver_user_id}</span>
              </td>
              <td className="muted">{a.txn_type}</td>
              <td className="num mono">{money(a.amount)}</td>
              <td>
                <ProbabilityPill
                  value={a.fraud_probability}
                  blockThreshold={blockThreshold}
                  alertThreshold={alertThreshold}
                />
              </td>
              <td>
                <span className={`status-chip status-chip-${a.alert_status}`}>
                  {a.alert_status.replace("_", " ")}
                </span>
              </td>
              <td className="muted reason-cell" title={a.block_reason || ""}>
                {a.block_reason || "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
