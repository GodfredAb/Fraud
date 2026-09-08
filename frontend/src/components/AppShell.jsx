const NAV_ITEMS = [
  { key: "dashboard", label: "Dashboard", icon: "◱" },
  { key: "alerts", label: "Alerts", icon: "▲" },
  { key: "accounts", label: "Accounts", icon: "◉" },
  { key: "map", label: "Map", icon: "▦" },
];

export function AppShell({ page, onNavigate, children }) {
  return (
    <div className="shell">
      <header className="topbar">
        <div className="topbar-brand">FRAUD_MONITOR</div>
        <nav className="topbar-tabs">
          <button
            className={`topbar-tab ${page === "dashboard" || page === "alerts" || page === "accounts" || page === "map" ? "topbar-tab-active" : ""}`}
            onClick={() => onNavigate("dashboard")}
          >
            Overview
          </button>
          <button
            className={`topbar-tab ${page === "reports" ? "topbar-tab-active" : ""}`}
            onClick={() => onNavigate("reports")}
          >
            Reports
          </button>
        </nav>
        <div className="topbar-search">
          <span className="topbar-search-icon" aria-hidden="true">⌕</span>
          <input type="text" placeholder="Search systems..." disabled title="Not wired up in this demo" />
        </div>
        <div className="topbar-icons">
          <button className="icon-button" title="Notifications (not wired up)" aria-label="Notifications">🔔</button>
          <button className="icon-button" title="Settings (not wired up)" aria-label="Settings">⚙</button>
          <button className="icon-button" title="Help (not wired up)" aria-label="Help">?</button>
          <div className="topbar-avatar" title="Signed in as Analyst" aria-hidden="true">A</div>
        </div>
      </header>

      <div className="shell-body">
        <aside className="sidebar">
          <div className="sidebar-header">
            <div className="sidebar-title">OPS_CENTER</div>
            <div className="sidebar-subtitle">Live Monitoring</div>
          </div>

          <nav className="sidebar-nav">
            {NAV_ITEMS.map((item) => (
              <button
                key={item.key}
                className={`sidebar-nav-item ${page === item.key ? "sidebar-nav-item-active" : ""}`}
                onClick={() => onNavigate(item.key)}
              >
                <span className="sidebar-nav-icon" aria-hidden="true">{item.icon}</span>
                {item.label}
              </button>
            ))}
          </nav>

          <button className="sidebar-new-report" onClick={() => onNavigate("reports")}>
            + New Report
          </button>

          <div className="sidebar-footer">
            <button className="sidebar-footer-link" title="Not wired up in this demo">Support</button>
            <button className="sidebar-footer-link" title="Not wired up in this demo">Logs</button>
          </div>
        </aside>

        <main className="shell-main">{children}</main>
      </div>
    </div>
  );
}
