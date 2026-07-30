import { useState } from "react";
import { api } from "./api";
import { usePolling } from "./hooks/usePolling";
import { AppShell } from "./components/AppShell";
import { StatTile } from "./components/StatTile";
import { AlertsTable } from "./components/AlertsTable";
import { RecentActivity } from "./components/RecentActivity";
import { SuspendedAccounts } from "./components/SuspendedAccounts";
import { FraudLocations } from "./components/FraudLocations";
import { ActivityFeed } from "./components/ActivityFeed";
import { TransactionDetail } from "./components/TransactionDetail";
import { shortMoney, ms } from "./format";
import "./App.css";

const POLL_MS = 4000;

function App() {
  const { data: stats, error: statsError } = usePolling(api.stats, POLL_MS);
  const { data: alerts } = usePolling(() => api.alerts(20), POLL_MS);
  const { data: recent } = usePolling(() => api.recentTransactions(15), POLL_MS);
  const { data: suspended } = usePolling(api.suspended, POLL_MS);
  const { data: fraudLocations } = usePolling(() => api.fraudLocations(20), POLL_MS);
  const [selectedTxnId, setSelectedTxnId] = useState(null);
  const [page, setPage] = useState("dashboard");

  const blockThreshold = stats?.block_threshold ?? 0.8;
  const alertThreshold = stats?.alert_threshold ?? 0.5;

  return (
    <AppShell page={page} onNavigate={setPage}>
      {statsError && (
        <div className="banner banner-error">
          Can't reach the API at the configured VITE_API_URL. Is <code>uvicorn api.main:app</code> running?
          <br />
          <span className="mono">{statsError}</span>
        </div>
      )}

      {page === "dashboard" && (
        <>
          <section className="stat-grid">
            <StatTile
              label="SYSTEM HEALTH"
              value={stats ? `${stats.system_health_pct}%` : "—"}
              tone="good"
              sublabel={stats ? `${stats.pending_transactions} pending` : undefined}
              icon="✓"
            />
            <StatTile
              label="ACTIVE ALERTS"
              value={stats ? stats.open_alerts.toLocaleString() : "—"}
              tone="critical"
              sublabel="High Priority"
              icon="!"
            />
            <StatTile
              label="FRAUD VOLUME"
              value={stats ? shortMoney(stats.fraud_volume_24h) : "—"}
              tone="warning"
              sublabel="Past 24h"
              icon="⛁"
            />
            <StatTile
              label="SCORING LATENCY"
              value={stats ? ms(stats.avg_scoring_latency_ms) : "—"}
              tone="neutral"
              sublabel={stats ? `P95: ${ms(stats.p95_scoring_latency_ms)}` : undefined}
              icon="◷"
            />
          </section>

          <div className="dash-grid">
            <section className="panel panel-main">
              <div className="panel-header">
                <h2>Fraud Alerts</h2>
                <span className="muted">Live Feed</span>
              </div>
              <AlertsTable
                alerts={alerts}
                blockThreshold={blockThreshold}
                alertThreshold={alertThreshold}
                onSelect={setSelectedTxnId}
              />
            </section>

            <div className="dash-side">
              <section className="panel">
                <div className="panel-header">
                  <h2>Activity Feed</h2>
                </div>
                <ActivityFeed alerts={alerts} suspended={suspended} />
              </section>

              <section className="panel">
                <div className="panel-header">
                  <h2>Suspended Accounts</h2>
                </div>
                <SuspendedAccounts accounts={suspended?.slice(0, 5)} />
              </section>
            </div>
          </div>

          <section className="panel">
            <div className="panel-header">
              <h2>Geo-Location Deltas</h2>
              <span className="muted">illustrative location resolution - synthetic data</span>
            </div>
            <FraudLocations rows={fraudLocations} onSelect={setSelectedTxnId} />
          </section>
        </>
      )}

      {page === "alerts" && (
        <>
          <section className="panel">
            <div className="panel-header">
              <h2>Fraud Alerts</h2>
              <span className="muted">newest first · polls every {POLL_MS / 1000}s</span>
            </div>
            <AlertsTable
              alerts={alerts}
              blockThreshold={blockThreshold}
              alertThreshold={alertThreshold}
              onSelect={setSelectedTxnId}
            />
          </section>
          <section className="panel">
            <div className="panel-header">
              <h2>Live Scoring Feed</h2>
              <span className="muted">most recently scored</span>
            </div>
            <RecentActivity
              transactions={recent}
              blockThreshold={blockThreshold}
              alertThreshold={alertThreshold}
              onSelect={setSelectedTxnId}
            />
          </section>
        </>
      )}

      {page === "accounts" && (
        <section className="panel">
          <div className="panel-header">
            <h2>Suspended Accounts</h2>
            <span className="muted">prevention: frozen after a hard block</span>
          </div>
          <SuspendedAccounts accounts={suspended} />
        </section>
      )}

      {page === "map" && (
        <section className="panel">
          <div className="panel-header">
            <h2>Map</h2>
          </div>
          <p className="muted" style={{ padding: "16px" }}>
            Map view isn't implemented in this demo - see the Geo-Location Deltas table on the
            Dashboard for the same data (current vs. home location per subscriber).
          </p>
        </section>
      )}

      {page === "reports" && (
        <section className="panel">
          <div className="panel-header">
            <h2>Reports</h2>
          </div>
          <p className="muted" style={{ padding: "16px" }}>Reports aren't implemented in this demo.</p>
        </section>
      )}

      {selectedTxnId != null && (
        <TransactionDetail txnId={selectedTxnId} onClose={() => setSelectedTxnId(null)} />
      )}
    </AppShell>
  );
}

export default App;
