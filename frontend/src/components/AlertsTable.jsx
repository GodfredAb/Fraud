import { ProbabilityPill } from "./ProbabilityPill";
import { classifyReason } from "../format";

const STATUS_MAP = {
  auto_blocked: { label: "Flagged", tone: "critical", icon: "⛔" },
  confirmed_fraud: { label: "Flagged", tone: "critical", icon: "⛔" },
  open: { label: "Pending", tone: "warning", icon: "◔" },
  under_review: { label: "Pending", tone: "warning", icon: "◔" },
  false_positive: { label: "Cleared", tone: "good", icon: "✓" },
};

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
            <th>ID</th>
            <th>Timestamp</th>
            <th>Type</th>
            <th>Probability</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {alerts.map((a) => {
            const status = STATUS_MAP[a.alert_status] || { label: a.alert_status, tone: "warning", icon: "◔" };
            return (
              <tr key={a.alert_id} className="clickable-row" onClick={() => onSelect?.(a.txn_id)}>
                <td className="mono link-cell">TRX_{a.txn_id}</td>
                <td className="muted">{new Date(a.alert_created_at).toLocaleTimeString()}</td>
                <td>{classifyReason(a.block_reason)}</td>
                <td>
                  <ProbabilityPill
                    value={a.fraud_probability}
                    blockThreshold={blockThreshold}
                    alertThreshold={alertThreshold}
                  />
                </td>
                <td>
                  <span className={`status-label status-label-${status.tone}`}>
                    <span aria-hidden="true">{status.icon}</span> {status.label}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
