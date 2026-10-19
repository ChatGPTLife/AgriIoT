import { useEffect, useState, useCallback, useRef } from "react";
import { api } from "../services/api";
import type {
  Zone, IrrigationDecision, ForecastDay, Alert, SensorReading, SystemStatus, ActivityEvent,
} from "../types";

const REC_TEXT: Record<string, string> = {
  IRRIGATION_REQUIRED: "irrigation required",
  WAIT_FOR_RAIN: "rain expected",
  NO_IRRIGATION_NEEDED: "no irrigation needed",
};
import { ZoneCard } from "../components/ZoneCard";
import { WeatherForecast } from "../components/WeatherForecast";
import { WeatherHero } from "../components/WeatherHero";
import { AlertBanner } from "../components/AlertBanner";
import { SensorForm } from "../components/SensorForm";
import { MoistureChart } from "../components/MoistureChart";
import { Icon } from "../components/Icon";

const POLL_MS = 6000;

interface Toast {
  id: string;
  title: string;
  body: string;
}

export const Dashboard: React.FC = () => {
  const [zones, setZones] = useState<Zone[]>([]);
  const [decisions, setDecisions] = useState<Record<string, IrrigationDecision>>({});
  const [forecasts, setForecasts] = useState<Record<string, ForecastDay[]>>({});
  const [activeAlerts, setActiveAlerts] = useState<Alert[]>([]);
  const [heroZoneId, setHeroZoneId] = useState<string | null>(null);
  const [readings, setReadings] = useState<Record<string, SensorReading[]>>({});
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [triggering, setTriggering] = useState(false);
  const [selectedZone, setSelectedZone] = useState<Zone | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const seenSms = useRef<Set<string> | null>(null);
  const seenEmail = useRef<Set<string> | null>(null);
  // Zones just triggered manually: their delivery toasts come from the trigger response instead.
  const manualUntil = useRef<Record<string, number>>({});
  const heroRef = useRef<string | null>(null);
  heroRef.current = heroZoneId;

  const pushToast = (t: Toast) => {
    setToasts((prev) => [...prev, t]);
    setTimeout(() => setToasts((prev) => prev.filter((x) => x.id !== t.id)), 8000);
  };

  const loadData = useCallback(async () => {
    try {
      setError(null);
      const { zones: zoneList } = await api.zones.list();
      zoneList.sort((a, b) => a.name.localeCompare(b.name));
      setZones(zoneList);
      let heroId = heroRef.current && zoneList.some((z) => z.zone_id === heroRef.current) ? heroRef.current : null;
      if (!heroId && zoneList.length) {
        // First load: open on the zone that currently has an active alert, if any.
        const active = await api.alerts.list({ status: "active" }).catch(() => ({ alerts: [] as Alert[] }));
        heroId = active.alerts.find((a) => zoneList.some((z) => z.zone_id === a.zone_id))?.zone_id ?? zoneList[0].zone_id;
      }
      if (heroId !== heroRef.current) setHeroZoneId(heroId);

      const [decisionResults, forecastResults, alertResult, readingResult, emailLog, smsLog, statusResult] =
        await Promise.allSettled([
          Promise.all(zoneList.map((z) =>
            api.irrigation.latestDecision(z.zone_id).then((r) => [z.zone_id, r.decision] as const))),
          Promise.all(zoneList.map((z) =>
            api.weather.get(z.zone_id).then((r) => [z.zone_id, r.forecast] as const).catch(() => [z.zone_id, []] as const))),
          api.alerts.list({ status: "active" }),
          heroId ? api.readings.list(heroId, 72) : Promise.resolve({ readings: [] as SensorReading[], count: 0 }),
          api.system.activity("email", 30),
          api.system.activity("sms", 20),
          api.system.status(),
        ]);

      if (decisionResults.status === "fulfilled") {
        setDecisions(Object.fromEntries(decisionResults.value.filter(([, d]) => d !== null).map(([id, d]) => [id, d!])));
      }
      if (forecastResults.status === "fulfilled") setForecasts(Object.fromEntries(forecastResults.value));
      if (alertResult.status === "fulfilled") {
        setActiveAlerts([...alertResult.value.alerts].sort((a, b) => b.created_at.localeCompare(a.created_at)));
      }
      if (readingResult.status === "fulfilled" && heroId) {
        setReadings((prev) => ({ ...prev, [heroId]: readingResult.value.readings }));
      }
      const isManual = (zoneId?: string) => !!zoneId && (manualUntil.current[zoneId] ?? 0) > Date.now();
      if (emailLog.status === "fulfilled") {
        const events = emailLog.value.events.filter((e) => e.kind === "alert");
        if (seenEmail.current === null) {
          seenEmail.current = new Set(events.map((e) => e.event_id));
        } else {
          const fresh = events.filter((e) => !seenEmail.current!.has(e.event_id));
          fresh.forEach((e) => seenEmail.current!.add(e.event_id));
          const byZone = new Map<string, ActivityEvent[]>();
          fresh.filter((e) => !isManual(e.zone_id)).forEach((e) => byZone.set(e.zone_id ?? "", [...(byZone.get(e.zone_id ?? "") ?? []), e]));
          byZone.forEach((list, zid) => {
            const zoneName = zoneList.find((z) => z.zone_id === zid)?.name ?? zid;
            const simulated = list.some((e) => e.status === "simulated");
            pushToast({
              id: `email-${list[0].event_id}`,
              title: `Email alert · ${zoneName}`,
              body: `Sent to ${list.length} subscriber${list.length > 1 ? "s" : ""}${simulated ? " (simulated)" : " via Gmail"}`,
            });
          });
        }
      }
      if (statusResult.status === "fulfilled") setStatus(statusResult.value);
      if (smsLog.status === "fulfilled") {
        const events = smsLog.value.events;
        if (seenSms.current === null) {
          seenSms.current = new Set(events.map((e) => e.event_id));
        } else {
          for (const e of [...events].reverse()) {
            if (seenSms.current.has(e.event_id)) continue;
            seenSms.current.add(e.event_id);
            if (isManual(e.zone_id)) continue;
            const zoneName = zoneList.find((z) => z.zone_id === e.zone_id)?.name ?? e.zone_id;
            pushToast({
              id: e.event_id,
              title: e.status === "sent" ? `SMS alert sent · ${zoneName}` : `SMS delivery failed · ${zoneName}`,
              body: e.status === "sent"
                ? `Amazon SNS → ${e.target}${e.delivery === "mock" ? " (simulated)" : ""}`
                : `Amazon SNS error: ${e.error ?? "unknown"}`,
            });
          }
        }
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load dashboard data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
    const id = setInterval(loadData, POLL_MS);
    return () => clearInterval(id);
  }, [loadData]);

  const selectHero = (id: string) => {
    setHeroZoneId(id);
    heroRef.current = id;
    loadData();
  };

  const handleTrigger = async (zone: Zone) => {
    setTriggering(true);
    manualUntil.current[zone.zone_id] = Date.now() + 20000;
    try {
      const { alert } = await api.alerts.trigger(zone.zone_id);
      const emails = alert.delivery.emails;
      const sent = emails.filter((e) => e.status !== "failed").length;
      const simulated = alert.delivery.sms_mode === "mock" || emails.some((e) => e.status === "simulated");
      pushToast({
        id: alert.alert_id,
        title: `Manual alert sent · ${zone.name}`,
        body: `${REC_TEXT[alert.recommendation ?? ""] ?? ""} · SMS via SNS + ${sent} email${sent === 1 ? "" : "s"}` +
          (emails.length > sent ? ` (${emails.length - sent} failed)` : "") +
          (emails.length === 0 ? " — no subscribers yet" : "") +
          (simulated ? " · simulated" : ""),
      });
      loadData();
    } catch (err: unknown) {
      pushToast({ id: `err-${Date.now()}`, title: "Couldn't trigger alert", body: err instanceof Error ? err.message : "Unknown error" });
    } finally {
      setTriggering(false);
    }
  };

  const handleAcknowledge = async (alertId: string) => {
    await api.alerts.acknowledge(alertId);
    setActiveAlerts((prev) => prev.filter((a) => a.alert_id !== alertId));
  };

  const latest = zones.map((z) => decisions[z.zone_id]).filter(Boolean);
  const needIrrigation = latest.filter((d) => d.recommendation === "IRRIGATION_REQUIRED").length;
  const avgMoisture = latest.length
    ? latest.reduce((sum, d) => sum + d.soil_moisture, 0) / latest.length
    : null;
  const heroZone = zones.find((z) => z.zone_id === heroZoneId) ?? null;

  if (loading) {
    return (
      <div className="page-loading">
        <div className="spinner" />
        <span>Loading dashboard…</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="page-error">
        <h2><Icon name="warning" size={18} />Couldn't load dashboard</h2>
        <p>{error}</p>
        <button onClick={loadData} className="btn-primary">Retry</button>
      </div>
    );
  }

  return (
    <div className="dashboard">
      {/* Summary */}
      <section className="kpi-row">
        <div className="kpi">
          <span className="kpi__label">Zones monitored<Icon name="pin" size={14} /></span>
          <span className="kpi__value">{zones.length}</span>
        </div>
        <div className={`kpi${needIrrigation > 0 ? " kpi--alert" : ""}`}>
          <span className="kpi__label">Need irrigation<Icon name="droplet" size={14} /></span>
          <span className="kpi__value">{needIrrigation}</span>
        </div>
        <div className={`kpi${activeAlerts.length > 0 ? " kpi--alert" : ""}`}>
          <span className="kpi__label">Active alerts<Icon name="bell" size={14} /></span>
          <span className="kpi__value">{activeAlerts.length}</span>
        </div>
        <div className="kpi">
          <span className="kpi__label">Avg. soil moisture<Icon name="activity" size={14} /></span>
          <span className="kpi__value">
            {avgMoisture !== null ? avgMoisture.toFixed(1) : "—"}
            {avgMoisture !== null && <span className="kpi__unit">%</span>}
          </span>
        </div>
      </section>

      {heroZone && (
        <WeatherHero
          zones={zones}
          zone={heroZone}
          onSelectZone={selectHero}
          forecast={forecasts[heroZone.zone_id] ?? []}
          readings={readings[heroZone.zone_id] ?? []}
          decision={decisions[heroZone.zone_id] ?? null}
          status={status}
          onTrigger={() => handleTrigger(heroZone)}
          triggering={triggering}
        />
      )}

      {/* Active alerts */}
      {activeAlerts.length > 0 && (
        <section className="dashboard__alerts-section">
          <h2 className="section-title" style={{ marginBottom: "1rem" }}>
            Active alerts <span className="badge badge-alert">{activeAlerts.length}</span>
          </h2>
          <div className="alerts-list">
            {activeAlerts.map((a) => (
              <AlertBanner key={a.alert_id} alert={a} onAcknowledge={handleAcknowledge} />
            ))}
          </div>
        </section>
      )}

      {/* Zone cards */}
      <section className="dashboard__zones-section">
        <div className="section-header">
          <h2 className="section-title">
            Agricultural zones
            <span className="live-pill"><span className="live-pill__dot" />Live · every {POLL_MS / 1000}s</span>
          </h2>
          <button className="btn-secondary" onClick={loadData} id="refresh-dashboard">
            <Icon name="refresh" size={14} />
            Refresh
          </button>
        </div>

        {zones.length === 0 ? (
          <div className="dashboard__empty">
            <p>No zones configured. Go to Zones to create one.</p>
          </div>
        ) : (
          <div className="zones-grid">
            {zones.map((zone) => (
              <ZoneCard
                key={zone.zone_id}
                zone={zone}
                decision={decisions[zone.zone_id] ?? null}
                onInspect={(z) => {
                  setSelectedZone(z);
                  selectHero(z.zone_id);
                }}
              />
            ))}
          </div>
        )}
      </section>

      {/* Zone detail panel */}
      {selectedZone && (
        <div className="zone-detail-overlay" onClick={() => setSelectedZone(null)}>
          <div className="zone-detail-panel" onClick={(e) => e.stopPropagation()}>
            <button className="zone-detail-panel__close" onClick={() => setSelectedZone(null)} id="close-zone-detail">
              <Icon name="x" />
            </button>
            <h2 className="zone-detail-panel__title">{selectedZone.name}</h2>
            <button
              className="btn-primary zone-detail-panel__trigger"
              onClick={() => handleTrigger(selectedZone)}
              disabled={triggering}
            >
              <Icon name="zap" size={14} />
              {triggering ? "Sending…" : "Trigger alert"}
            </button>
            <p className="zone-detail-panel__coords">
              <Icon name="pin" size={13} />{selectedZone.latitude.toFixed(4)}, {selectedZone.longitude.toFixed(4)}
            </p>

            <h3 className="zone-detail-panel__subtitle">Soil moisture · 72 hours</h3>
            <MoistureChart
              readings={readings[selectedZone.zone_id] ?? []}
              threshold={selectedZone.moisture_threshold}
              target={selectedZone.target_moisture}
              height={180}
            />

            <h3 className="zone-detail-panel__subtitle" style={{ marginTop: "1.5rem" }}>7-day forecast</h3>
            <WeatherForecast forecast={forecasts[selectedZone.zone_id] ?? []} />

            <h3 className="zone-detail-panel__subtitle" style={{ marginTop: "1.5rem" }}>
              Submit sensor reading
            </h3>
            <SensorForm
              zoneId={selectedZone.zone_id}
              zoneName={selectedZone.name}
              onSuccess={() => loadData()}
            />
          </div>
        </div>
      )}

      {/* Toasts */}
      <div className="toasts" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className="toast">
            <span className="toast__icon"><Icon name="message" size={16} /></span>
            <div>
              <strong>{t.title}</strong>
              <p>{t.body}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
