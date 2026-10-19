import { useEffect, useState, useCallback } from "react";
import { api } from "../services/api";
import type { Alert } from "../types";
import { AlertBanner } from "../components/AlertBanner";
import { Icon } from "../components/Icon";

export const Alerts: React.FC = () => {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [filter, setFilter] = useState<"all" | "active" | "acknowledged">("active");
  const [loading, setLoading] = useState(true);

  const loadAlerts = useCallback(async () => {
    setLoading(true);
    const { alerts: list } = await api.alerts.list(
      filter === "all" ? {} : { status: filter }
    );
    setAlerts(list);
    setLoading(false);
  }, [filter]);

  useEffect(() => { loadAlerts(); }, [loadAlerts]);

  const handleAcknowledge = async (alertId: string) => {
    await api.alerts.acknowledge(alertId);
    await loadAlerts();
  };

  const activeCount = alerts.filter((a) => a.status === "active").length;

  return (
    <div className="alerts-page">
      <div className="section-header">
        <h1 className="page-title">
          Alerts {activeCount > 0 && <span className="badge badge-alert">{activeCount} active</span>}
        </h1>
        <button className="btn-secondary" onClick={loadAlerts} id="refresh-alerts">
          <Icon name="refresh" size={14} />
          Refresh
        </button>
      </div>

      {/* Filter tabs */}
      <div className="filter-tabs">
        {(["active", "all", "acknowledged"] as const).map((f) => (
          <button
            key={f}
            className={`filter-tab${filter === f ? " filter-tab--active" : ""}`}
            onClick={() => setFilter(f)}
            id={`filter-${f}`}
          >
            {f.charAt(0).toUpperCase() + f.slice(1)}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="page-loading"><div className="spinner" /></div>
      ) : alerts.length === 0 ? (
        <div className="dashboard__empty">
          <p>
            {filter === "active"
              ? "No active alerts. All zones are in good condition."
              : "No alerts found."}
          </p>
        </div>
      ) : (
        <div className="alerts-list">
          {alerts.map((a) => (
            <AlertBanner key={a.alert_id} alert={a} onAcknowledge={handleAcknowledge} />
          ))}
        </div>
      )}
    </div>
  );
};
