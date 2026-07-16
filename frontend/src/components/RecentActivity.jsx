import { ProbabilityPill } from "./ProbabilityPill";
import { relativeTime, money } from "../format";

export function RecentActivity({ transactions, blockThreshold, alertThreshold }) {
  if (!transactions) {
    return <p className="muted">Loading…</p>;
  }
  if (transactions.length === 0) {
    return <p className="muted">Nothing scored yet - start feeder.py and monitor.py.</p>;
  }

  return (
    <div className="table-scroll">
      <table className="data-table compact">
        <thead>
          <tr>
            <th>Scored</th>
            <th>Txn</th>
            <th>Sender → Receiver</th>
            <th className="num">Amount</th>
            <th>Fraud probability</th>
          </tr>
        </thead>
        <tbody>
          {transactions.map((t) => (
            <tr key={t.txn_id}>
              <td className="muted">{relativeTime(t.scored_at)}</td>
              <td className="mono">#{t.txn_id}</td>
              <td className="muted">
                {t.sender_user_id} → {t.receiver_user_id}
              </td>
              <td className="num mono">{money(t.amount)}</td>
              <td>
                <ProbabilityPill
                  value={t.fraud_probability}
                  blockThreshold={blockThreshold}
                  alertThreshold={alertThreshold}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
