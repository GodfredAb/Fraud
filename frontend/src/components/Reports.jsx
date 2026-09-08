import { useEffect, useState } from "react";
import { api } from "../api";
import { StatTile } from "./StatTile";
import { shortMoney, classifyReason, downloadCsv } from "../format";

const RANGES = [
  { key: "today", label: "Today" },
  { key: "7d", label: "7 Days" },
  { key: "30d", label: "30 Days" },
  { key: "all", label: "All Time" },
];

const CSV_COLUMNS = [
  ["txn_id", "Txn ID"],
  ["alert_created_at", "Flagged At"],
  ["sender_user_id", "Sender ID"],
  ["sender_name", "Sender Name"],
  ["receiver_user_id", "Receiver ID"],
  ["txn_type", "Type"],
  ["amount", "Amount"],
  ["fraud_probability", "Fraud Probability"],
  ["blocked", "Blocked"],
  ["alert_status", "Status"],
  ["block_reason", "Reason"],
];

/**
 * A real, on-demand report (not part of the 4s steady poll loop, like
 * TransactionDetail) over a chosen time window - summary stats, a rule/type
 * breakdown, and the top flagged subscribers, all derived from the actual
 * alert rows /api/reports returns for that window, plus a genuine client-
 * side CSV export (no server round trip) and a real print button.
 */
export function Reports() {
  const [range, setRange] = useState("7d");
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setData(null);
    setError(null);
    api.reports(range).then(setData).catch((e) => setError(String(e)));
  }, [range]);

  if (error) return <p className="banner banner-error">{error}</p>;
  if (!data) return <p className="muted" style={{ padding: "16px" }}>Loading report…</p>;

  const { summary, alerts } = data;

  // Rule/type breakdown - the SAME categorization the Fraud Alerts table's
  // Type column uses (classifyReason), not a second implementation.
  const typeCounts = {};
  for (const a of alerts) {
    const type = classifyReason(a.block_reason);
    typeCounts[type] = (typeCounts[type] || 0) + 1;
  }
  const typeBreakdown = Object.entries(typeCounts).sort((a, b) => b[1] - a[1]);
  const maxTypeCount = typeBreakdown[0]?.[1] || 1;

  const bySender = {};
  for (const a of alerts) {
    const key = a.sender_user_id;
    if (!bySender[key]) bySender[key] = { name: a.sender_name, id: key, count: 0, maxProb: 0 };
    bySender[key].count += 1;
    bySender[key].maxProb = Math.max(bySender[key].maxProb, a.fraud_probability);
  }
  const topSenders = Object.values(bySender).sort((a, b) => b.count - a.count).slice(0, 10);

  function exportCsv() {
    downloadCsv(`fraud-report-${range}-${new Date().toISOString().slice(0, 10)}.csv`, alerts, CSV_COLUMNS);
  }

  return (
    <>
      <section className="report-controls">
        <div className="report-range-picker">
          {RANGES.map((r) => (
            <button
              key={r.key}
              className={`report-range-btn ${range === r.key ? "report-range-btn-active" : ""}`}
              onClick={() => setRange(r.key)}
            >
              {r.label}
            </button>
          ))}
        </div>
        <div className="report-actions">
          <button className="report-action-btn" onClick={exportCsv} disabled={alerts.length === 0}>
            ⭳ Export CSV
          </button>
          <button className="report-action-btn" onClick={() => window.print()}>⎙ Print</button>
        </div>
      </section>

      <section className="stat-grid">
        <StatTile label="TRANSACTIONS SCORED" value={summary.total_scored.toLocaleString()} tone="neutral" icon="◱" />
        <StatTile label="FLAGGED" value={summary.flagged_count.toLocaleString()} tone="warning" icon="▲" />
        <StatTile
          label="BLOCKED"
          value={summary.blocked_count.toLocaleString()}
          tone="critical"
          icon="⛔"
          sublabel={`${shortMoney(summary.protected_volume)} protected`}
        />
        <StatTile
          label="AVG FRAUD PROBABILITY"
          value={summary.avg_fraud_probability != null ? `${Math.round(summary.avg_fraud_probability * 100)}%` : "—"}
          tone="good"
          icon="✓"
        />
      </section>

      <div className="dash-grid">
        <section className="panel">
          <div className="panel-header">
            <h2>Rule Breakdown</h2>
            <span className="muted">{alerts.length} alert{alerts.length === 1 ? "" : "s"} in range</span>
          </div>
          {typeBreakdown.length === 0 ? (
            <p className="muted" style={{ padding: "16px" }}>No alerts in this range.</p>
          ) : (
            <div className="type-bars">
              {typeBreakdown.map(([type, count]) => (
                <div className="type-bar-row" key={type}>
                  <span className="type-bar-label">{type}</span>
                  <div className="type-bar-track">
                    <div className="type-bar-fill" style={{ width: `${(count / maxTypeCount) * 100}%` }} />
                  </div>
                  <span className="type-bar-value mono">{count}</span>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="panel">
          <div className="panel-header">
            <h2>Top Flagged Subscribers</h2>
          </div>
          {topSenders.length === 0 ? (
            <p className="muted" style={{ padding: "16px" }}>No alerts in this range.</p>
          ) : (
            <ul className="suspended-list">
              {topSenders.map((s) => (
                <li key={s.id} className="suspended-item">
                  <div>
                    <div className="suspended-item-name">{s.name} <span className="muted mono">({s.id})</span></div>
                    <div className="muted">{s.count} alert{s.count === 1 ? "" : "s"} · max {Math.round(s.maxProb * 100)}%</div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </>
  );
}
