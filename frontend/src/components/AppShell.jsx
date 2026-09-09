import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { money, relativeTime } from "../format";

const NAV_ITEMS = [
  { key: "dashboard", label: "Dashboard", icon: "◱" },
  { key: "alerts", label: "Alerts", icon: "▲" },
  { key: "accounts", label: "Accounts", icon: "◉" },
  { key: "subscribers", label: "Subscribers", icon: "☺" },
  { key: "map", label: "Map", icon: "▦" },
];

const HELP_SECTIONS = [
  ["What this dashboard shows", "Every mobile money transaction the system has scored, in real time - what the ensemble (XGBoost + Isolation Forest + Local Outlier Factor + a rule engine) decided, and why."],
  ["Approve / Flag / Block", "Every scored transaction lands in exactly one of three outcomes: auto-approved (clean, no review needed), flagged (queued for analyst review), or blocked + the sender suspended (high-confidence fraud, stopped automatically)."],
  ["Subscribers", "Search the subscriber directory by name, ID, or phone number to open a full profile - identity, device, location, and the behavioral baseline (average spend, transaction count, counterparties) the model scores new activity against."],
  ["Map & Reports", "The Map plots current vs. home location for the highest-risk subscribers. Reports lets you pull a rule breakdown and export a CSV for any date range."],
];

function useOutsideClick(ref, onOutside) {
  useEffect(() => {
    function handler(e) {
      if (ref.current && !ref.current.contains(e.target)) onOutside();
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [ref, onOutside]);
}

function SearchBox({ onSelectTxn, onSelectSubscriber }) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState(null);
  const [open, setOpen] = useState(false);
  const boxRef = useRef(null);
  useOutsideClick(boxRef, () => setOpen(false));

  useEffect(() => {
    if (!q.trim()) {
      setResults(null);
      return undefined;
    }
    let cancelled = false;
    const handle = setTimeout(() => {
      api.search(q.trim()).then((r) => !cancelled && setResults(r)).catch(() => !cancelled && setResults(null));
    }, 200);
    return () => {
      cancelled = true;
      clearTimeout(handle);
    };
  }, [q]);

  const hasResults = results && (results.transactions.length > 0 || results.subscribers.length > 0);

  return (
    <div className="topbar-search" ref={boxRef}>
      <span className="topbar-search-icon" aria-hidden="true">⌕</span>
      <input
        type="text"
        placeholder="Search transactions or subscribers…"
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
      />
      {open && q.trim() && (
        <div className="search-dropdown">
          {!results && <div className="search-dropdown-empty muted">Searching…</div>}
          {results && !hasResults && <div className="search-dropdown-empty muted">No matches.</div>}
          {results?.subscribers.length > 0 && (
            <div className="search-dropdown-group">
              <div className="search-dropdown-label">Subscribers</div>
              {results.subscribers.map((s) => (
                <button
                  key={s.user_id}
                  className="search-dropdown-item"
                  onClick={() => {
                    onSelectSubscriber(s.user_id);
                    setOpen(false);
                    setQ("");
                  }}
                >
                  {s.full_name} <span className="muted">({s.user_id}) · {s.msisdn}</span>
                </button>
              ))}
            </div>
          )}
          {results?.transactions.length > 0 && (
            <div className="search-dropdown-group">
              <div className="search-dropdown-label">Transactions</div>
              {results.transactions.map((t) => (
                <button
                  key={t.txn_id}
                  className="search-dropdown-item"
                  onClick={() => {
                    onSelectTxn(t.txn_id);
                    setOpen(false);
                    setQ("");
                  }}
                >
                  #{t.txn_id} <span className="muted">{t.sender_user_id} → {t.receiver_user_id} · {money(t.amount)}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function NotificationsMenu({ alerts, onSelectTxn }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useOutsideClick(ref, () => setOpen(false));
  const items = (alerts || []).slice(0, 6);

  return (
    <div className="icon-menu" ref={ref}>
      <button className="icon-button" onClick={() => setOpen((v) => !v)} aria-label="Notifications">
        🔔{items.length > 0 && <span className="icon-badge">{items.length}</span>}
      </button>
      {open && (
        <div className="icon-dropdown">
          <div className="icon-dropdown-title">Recent alerts</div>
          {items.length === 0 && <div className="muted" style={{ padding: "10px 12px" }}>No open alerts.</div>}
          {items.map((a) => (
            <button
              key={a.alert_id ?? a.txn_id}
              className="search-dropdown-item"
              onClick={() => {
                onSelectTxn(a.txn_id);
                setOpen(false);
              }}
            >
              #{a.txn_id} <span className="muted">{money(a.amount)} · {relativeTime(a.alert_created_at || a.scored_at)}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function SettingsMenu() {
  const [open, setOpen] = useState(false);
  const [cfg, setCfg] = useState(null);
  const ref = useRef(null);
  useOutsideClick(ref, () => setOpen(false));

  function toggle() {
    setOpen((v) => !v);
    if (!cfg) api.config().then(setCfg).catch(() => {});
  }

  return (
    <div className="icon-menu" ref={ref}>
      <button className="icon-button" onClick={toggle} aria-label="Settings">⚙</button>
      {open && (
        <div className="icon-dropdown icon-dropdown-wide">
          <div className="icon-dropdown-title">Live system configuration</div>
          {!cfg && <div className="muted" style={{ padding: "10px 12px" }}>Loading…</div>}
          {cfg && (
            <div className="settings-grid">
              <div>Alert threshold</div><div>{cfg.alert_threshold}</div>
              <div>Block threshold</div><div>{cfg.block_threshold}</div>
              <div>XGBoost weight</div><div>{cfg.ensemble_weights.xgboost}</div>
              <div>Isolation Forest weight</div><div>{cfg.ensemble_weights.isolation_forest}</div>
              <div>LOF weight</div><div>{cfg.ensemble_weights.lof}</div>
              <div>Rule engine weight</div><div>{cfg.ensemble_weights.rules}</div>
              <div>Feeder batch size</div><div>{cfg.feeder_batch_size}</div>
              <div>Monitor poll interval</div><div>{cfg.monitor_poll_interval_seconds}s</div>
              <div>Session length</div><div>{cfg.session_ttl_hours}h</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function HelpMenu() {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useOutsideClick(ref, () => setOpen(false));

  return (
    <div className="icon-menu" ref={ref}>
      <button className="icon-button" onClick={() => setOpen((v) => !v)} aria-label="Help">?</button>
      {open && (
        <div className="icon-dropdown icon-dropdown-wide">
          {HELP_SECTIONS.map(([title, body]) => (
            <div key={title} className="help-section">
              <div className="help-section-title">{title}</div>
              <div className="muted">{body}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ProfileMenu({ analystName, onLogout }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useOutsideClick(ref, () => setOpen(false));
  const initial = (analystName || "?").charAt(0).toUpperCase();

  return (
    <div className="icon-menu" ref={ref}>
      <button className="topbar-avatar" onClick={() => setOpen((v) => !v)} title={`Signed in as ${analystName}`}>
        {initial}
      </button>
      {open && (
        <div className="icon-dropdown">
          <div className="icon-dropdown-title">Signed in as {analystName}</div>
          <button className="search-dropdown-item" onClick={onLogout}>Log out</button>
        </div>
      )}
    </div>
  );
}

export function AppShell({ page, onNavigate, analystName, onLogout, alerts, onSelectTxn, onSelectSubscriber, children }) {
  return (
    <div className="shell">
      <header className="topbar">
        <div className="topbar-brand">GROUP 13</div>
        <nav className="topbar-tabs">
          <button
            className={`topbar-tab ${page === "dashboard" || page === "alerts" || page === "accounts" || page === "subscribers" || page === "map" ? "topbar-tab-active" : ""}`}
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
        <SearchBox onSelectTxn={onSelectTxn} onSelectSubscriber={onSelectSubscriber} />
        <div className="topbar-icons">
          <NotificationsMenu alerts={alerts} onSelectTxn={onSelectTxn} />
          <SettingsMenu />
          <HelpMenu />
          <ProfileMenu analystName={analystName} onLogout={onLogout} />
        </div>
      </header>

      <div className="shell-body">
        <aside className="sidebar">
          <div className="sidebar-header">
            <div className="sidebar-title">SHIELD</div>
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
            <a className="sidebar-footer-link" href="mailto:support@shield-momo.example">Support</a>
            <button className="sidebar-footer-link" onClick={() => onNavigate("logs")}>Logs</button>
          </div>
        </aside>

        <main className="shell-main">{children}</main>
      </div>
    </div>
  );
}
