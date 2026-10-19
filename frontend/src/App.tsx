import { useState } from "react";
import { Dashboard } from "./pages/Dashboard";
import { Zones } from "./pages/Zones";
import { Alerts } from "./pages/Alerts";
import { Integrations } from "./pages/Integrations";
import { Notifications } from "./pages/Notifications";
import { Icon, type IconName } from "./components/Icon";
import { useTheme } from "./theme";
import "./index.css";
import "./features.css";
import "./notifications.css";

type Page = "dashboard" | "zones" | "alerts" | "notifications" | "integrations";

const NAV: { id: Page; label: string; icon: IconName }[] = [
  { id: "dashboard", label: "Dashboard", icon: "dashboard" },
  { id: "zones", label: "Zones", icon: "pin" },
  { id: "alerts", label: "Alerts", icon: "bell" },
  { id: "notifications", label: "Email alerts", icon: "mail" },
  { id: "integrations", label: "Integrations", icon: "plug" },
];

export default function App() {
  const [page, setPageState] = useState<Page>(() => {
    const hash = window.location.hash.slice(1);
    return NAV.some((n) => n.id === hash) ? (hash as Page) : "dashboard";
  });
  const setPage = (p: Page) => {
    setPageState(p);
    window.history.replaceState(null, "", `#${p}`);
  };
  const { theme, toggle } = useTheme();

  return (
    <div className="app">
      {/* Sidebar nav */}
      <nav className="sidebar">
        <div className="sidebar__brand">
          <span className="sidebar__logo"><Icon name="sprout" size={18} /></span>
          <span className="sidebar__title">AgriIoT</span>
        </div>
        <ul className="sidebar__nav">
          {NAV.map(({ id, label, icon }) => (
            <li key={id}>
              <button
                className={`sidebar__nav-item${page === id ? " sidebar__nav-item--active" : ""}`}
                onClick={() => setPage(id)}
                id={`nav-${id}`}
              >
                <Icon name={icon} className="sidebar__nav-icon" />
                <span>{label}</span>
              </button>
            </li>
          ))}
        </ul>
        <div className="sidebar__footer">
          <span className="status-dot" />
          <span>API Gateway · Lambda · SNS</span>
        </div>
      </nav>

      {/* Main content */}
      <main className="main-content">
        <header className="topbar">
          <h1 className="topbar__page-title">{NAV.find((n) => n.id === page)?.label}</h1>
          <div className="topbar__right">
            <span className="topbar__env-badge">AWS · IoT Monitor</span>
            <button
              className="theme-toggle"
              onClick={toggle}
              id="theme-toggle"
              aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
              title={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
            >
              <Icon name={theme === "dark" ? "sun" : "moon"} />
            </button>
          </div>
        </header>

        <div className="page-content">
          {page === "dashboard" && <Dashboard />}
          {page === "zones" && <Zones />}
          {page === "alerts" && <Alerts />}
          {page === "notifications" && <Notifications />}
          {page === "integrations" && <Integrations />}
        </div>
      </main>
    </div>
  );
}
