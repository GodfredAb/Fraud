import { relativeTime } from "../format";

export function SuspendedAccounts({ accounts }) {
  if (!accounts) {
    return <p className="muted">Loading…</p>;
  }
  if (accounts.length === 0) {
    return <p className="muted">No accounts currently suspended.</p>;
  }

  return (
    <ul className="suspended-list">
      {accounts.map((u) => (
        <li key={u.user_id} className="suspended-item">
          <span className="status-dot status-dot-critical" aria-hidden="true" />
          <div className="suspended-item-body">
            <div className="suspended-item-name">
              {u.full_name} <span className="muted mono">({u.user_id})</span>
            </div>
            <div className="muted">
              suspended {relativeTime(u.updated_at)} · {u.blocked_txn_count} blocked txn
              {u.blocked_txn_count === 1 ? "" : "s"}
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}
