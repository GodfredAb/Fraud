import { useState } from "react";
import { api } from "./api";
import { usePolling } from "./hooks/usePolling";
import { StatTile } from "./components/StatTile";
import { AlertsTable } from "./components/AlertsTable";
import { RecentActivity } from "./components/RecentActivity";
import { SuspendedAccounts } from "./components/SuspendedAccounts";
import { TransactionDetail } from "./components/TransactionDetail";
import { FraudLocations } from "./components/FraudLocations";
import { relativeTime } from "./format";
import "./App.css";

const POLL_MS = 4000;

function App() {
  const { data: stats, error: statsError, lastUpdated } = usePolling(api.stats, POLL_MS);
  const { data: alerts } = usePolling(() => api.alerts(20), POLL_MS);
  const { data: recent } = usePolling(() => api.recentTransactions(15), POLL_MS);
  const { data: suspended } = usePolling(api.suspended, POLL_MS);
  const { data: fraudLocations } = usePolling(() => api.fraudLocations(20), POLL_MS);
  const [selectedTxnId, setSelectedTxnId] = useState(null);

  const blockThreshold = stats?.block_threshold ?? 0.8;
  const alertThreshold = stats?.alert_threshold ?? 0.5;

  return (
    <div className="dashboard">
      <header className="dashboard-header">
        <div>
          <h1>Mobile Money Fraud Monitor</h1>
          <p className="muted">
            Live ensemble scoring - XGBoost + Isolation Forest + Local Outlier Factor + rule engine
          </p>
        </div>
        <div className="live-indicator">
          <span className={`live-dot ${statsError ? "live-dot-error" : ""}`} />
          {statsError ? "connection lost - retrying…" : `updated ${relativeTime(lastUpdated?.toISOString())}`}
        </div>
      </header>

      {statsError && (
        <div className="banner banner-error">
          Can't reach the API at the configured VITE_API_URL. Is <code>uvicorn api.main:app</code> running?
          <br />
          <span className="mono">{statsError}</span>
        </div>
      )}

      <section className="stat-grid">
        <StatTile label="Total transactions" value={stats ? stats.total_transactions.toLocaleString() : "—"} />
        <StatTile
          label="Pending"
          value={stats ? stats.pending_transactions.toLocaleString() : "—"}
          sublabel="not yet scored"
        />
        <StatTile
          label="Flagged"
          value={stats ? stats.flagged_transactions.toLocaleString() : "—"}
          tone="warning"
          sublabel={stats ? `≥ ${Math.round(alertThreshold * 100)}% probability` : undefined}
        />
        <StatTile
          label="Blocked"
          value={stats ? stats.blocked_transactions.toLocaleString() : "—"}
          tone="critical"
          sublabel={stats ? `≥ ${Math.round(blockThreshold * 100)}% probability` : undefined}
        />
        <StatTile
          label="Suspended accounts"
          value={stats ? `${stats.suspended_accounts} / ${stats.total_accounts}` : "—"}
          tone="critical"
        />
        <StatTile
          label="Open alerts"
          value={stats ? stats.open_alerts.toLocaleString() : "—"}
          tone={stats?.open_alerts > 0 ? "warning" : "good"}
          sublabel="awaiting review"
        />
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Fraud alert queue</h2>
          <span className="muted">newest first · polls every {POLL_MS / 1000}s</span>
        </div>
        <AlertsTable
          alerts={alerts}
          blockThreshold={blockThreshold}
          alertThreshold={alertThreshold}
          onSelect={setSelectedTxnId}
        />
      </section>

      <div className="panel-row">
        <section className="panel panel-half">
          <div className="panel-header">
            <h2>Live scoring feed</h2>
            <span className="muted">most recently scored</span>
          </div>
          <RecentActivity
            transactions={recent}
            blockThreshold={blockThreshold}
            alertThreshold={alertThreshold}
            onSelect={setSelectedTxnId}
          />
        </section>

        <section className="panel panel-half">
          <div className="panel-header">
            <h2>Suspended accounts</h2>
            <span className="muted">prevention: frozen after a hard block</span>
          </div>
          <SuspendedAccounts accounts={suspended} />
        </section>
      </div>

      <section className="panel">
        <div className="panel-header">
          <h2>Fraud subscriber locations</h2>
          <span className="muted">ranked by fraud probability - current vs. home location</span>
        </div>
        <FraudLocations rows={fraudLocations} />
      </section>

      {selectedTxnId != null && (
        <TransactionDetail txnId={selectedTxnId} onClose={() => setSelectedTxnId(null)} />
      )}
    </div>
  );
}

export default App;
