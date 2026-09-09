import { relativeTime } from "../format";

export function SuspendedAccounts({ accounts, onSelect }) {
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
          <div>
            <div className="suspended-item-name">{u.full_name || u.user_id}</div>
            <div className="muted">
              Suspended {relativeTime(u.updated_at)} · {u.blocked_txn_count} blocked txn
              {u.blocked_txn_count === 1 ? "" : "s"}
            </div>
          </div>
          <button
            className="icon-button"
            title={`View ${u.full_name} (${u.user_id})`}
            onClick={() => onSelect?.(u.user_id)}
          >
            👁
          </button>
        </li>
      ))}
    </ul>
  );
}
