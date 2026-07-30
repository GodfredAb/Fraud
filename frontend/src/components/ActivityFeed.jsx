import { relativeTime } from "../format";

/**
 * Built entirely from data already on screen elsewhere (alerts + suspended
 * accounts) - no separate audit-log table exists, and no fake "Analyst_04
 * reviewed..." entries are fabricated here: every line is a real system
 * action (a block, a suspension) with a real timestamp. Merged and
 * re-sorted client-side since the two source lists poll independently.
 */
export function ActivityFeed({ alerts, suspended }) {
  if (!alerts || !suspended) {
    return <p className="muted">Loading…</p>;
  }

  const events = [
    ...alerts
      .filter((a) => a.blocked)
      .map((a) => ({
        at: a.alert_created_at,
        title: `System blocked ${a.sender_name || a.sender_user_id}`,
        detail: (a.block_reason || "").split(";")[0] || "Rule triggered",
      })),
    ...suspended.map((u) => ({
      at: u.updated_at,
      title: `System suspended ${u.full_name || u.user_id}`,
      detail: `${u.blocked_txn_count} blocked transaction${u.blocked_txn_count === 1 ? "" : "s"}`,
    })),
  ]
    .sort((a, b) => new Date(b.at) - new Date(a.at))
    .slice(0, 8);

  if (events.length === 0) {
    return <p className="muted">No system actions yet.</p>;
  }

  return (
    <ul className="activity-feed">
      {events.map((e, i) => (
        <li key={i} className="activity-item">
          <span className="activity-bar" aria-hidden="true" />
          <div>
            <div className="activity-title">{e.title}</div>
            <div className="activity-detail">{e.detail}</div>
            <div className="activity-time">{relativeTime(e.at)}</div>
          </div>
        </li>
      ))}
    </ul>
  );
}
