import { useState } from "react";
import { api } from "./api";
import { usePolling } from "./hooks/usePolling";
import { AppShell } from "./components/AppShell";
import { StatTile } from "./components/StatTile";
import { AlertsTable } from "./components/AlertsTable";
import { RecentActivity } from "./components/RecentActivity";
import { SuspendedAccounts } from "./components/SuspendedAccounts";
import { FraudLocations } from "./components/FraudLocations";
import { FraudMap } from "./components/FraudMap";
import { Reports } from "./components/Reports";
import { ActivityFeed } from "./components/ActivityFeed";
import { TransactionDetail } from "./components/TransactionDetail";
import { shortMoney, ms } from "./format";
import "./App.css";

const POLL_MS = 4000;

function App() {
  const [selectedTxnId, setSelectedTxnId] = useState(null);
  const [page, setPage] = useState("dashboard");

  // Each panel's data only polls while a page that actually shows it is
  // active - no point fetching fraud-locations every 4s while looking at
  // the Map placeholder, and it was adding up: 5 endpoints x every page,
  // all the time, was part of what made the whole app feel slow.
  const { data: stats, error: statsError } = usePolling(api.stats, POLL_MS, [], page === "dashboard");
  const { data: alerts } = usePolling(() => api.alerts(20), POLL_MS, [], page === "dashboard" || page === "alerts");
  const { data: recent } = usePolling(() => api.recentTransactions(15), POLL_MS, [], page === "alerts");
  const { data: suspended } = usePolling(api.suspended, POLL_MS, [], page === "dashboard" || page === "accounts");
  const { data: fraudLocations } = usePolling(() => api.fraudLocations(20), POLL_MS, [], page === "dashboard");
  // Map view pulls a wider slice than the dashboard's top-20-worst-ever
  // panel - with users now spread across 10 regions, the worst-ever list
  // is dominated by a handful of long-history accounts in Accra, so the
  // map needs more rows to actually show the regional spread on it.
  const { data: mapLocations } = usePolling(() => api.fraudLocations(100), POLL_MS, [], page === "map");

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
            <StatTile
              label="AUTO-APPROVED"
              value={stats ? stats.approved_24h.toLocaleString() : "—"}
              tone="good"
              sublabel="Past 24h, no review needed"
              icon="✓"
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
            <h2>Fraud Location Map</h2>
            <span className="muted">illustrative location resolution - synthetic data</span>
          </div>
          <FraudMap
            rows={mapLocations}
            blockThreshold={blockThreshold}
            alertThreshold={alertThreshold}
            onSelect={setSelectedTxnId}
          />
        </section>
      )}

      {page === "reports" && <Reports />}

      {selectedTxnId != null && (
        <TransactionDetail txnId={selectedTxnId} onClose={() => setSelectedTxnId(null)} />
      )}
    </AppShell>
  );
}

export default App;
