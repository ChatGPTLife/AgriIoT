import { useCallback, useEffect, useState } from "react";
import { api } from "../services/api";
import type { ActivityEvent, SystemStatus } from "../types";
import { Icon } from "../components/Icon";
import { clockTime, timeAgo } from "../utils/time";

const POLL_MS = 4000;

function StatusDot({ ok }: { ok: boolean | null }) {
  return <span className={`dot ${ok === null ? "dot--idle" : ok ? "dot--ok" : "dot--error"}`} />;
}

export const Integrations: React.FC = () => {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [weatherCalls, setWeatherCalls] = useState<ActivityEvent[]>([]);
  const [sensorCalls, setSensorCalls] = useState<ActivityEvent[]>([]);
  const [filter, setFilter] = useState<"all" | "weather" | "sensor">("all");
  const [smsLog, setSmsLog] = useState<ActivityEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [, setTick] = useState(0);

  const load = useCallback(async () => {
    try {
      const [s, w, r, m] = await Promise.all([
        api.system.status(),
        api.system.activity("weather", 40),
        api.system.activity("sensor", 60),
        api.system.activity("sms", 30),
      ]);
      setStatus(s);
      setWeatherCalls(w.events);
      setSensorCalls(r.events);
      setSmsLog(m.events);
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load integration status");
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(() => { load(); setTick((t) => t + 1); }, POLL_MS);
    return () => clearInterval(id);
  }, [load]);

  const lastWeather = weatherCalls[0] ?? null;
  const apiLog = (filter === "weather" ? weatherCalls : filter === "sensor" ? sensorCalls : [...weatherCalls, ...sensorCalls])
    .slice()
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
    .slice(0, 80);
  const lastSms = smsLog[0] ?? null;
  const weatherOkCount = weatherCalls.filter((e) => e.status === "success").length;
  const avgLatency = weatherCalls.length
    ? Math.round(weatherCalls.reduce((s, e) => s + (e.latency_ms ?? 0), 0) / weatherCalls.length)
    : null;

  if (error && !status) {
    return (
      <div className="page-error">
        <h2><Icon name="warning" size={18} />Couldn't reach the API</h2>
        <p>{error}</p>
      </div>
    );
  }

  return (
    <div className="integrations">
      <div className="section-header">
        <div>
          <h1 className="page-title">API integrations</h1>
          <p className="page-subtitle">
            Every outbound call to the weather provider and every SMS published to Amazon SNS is logged here as it happens.
          </p>
        </div>
        <span className="live-pill"><span className="live-pill__dot" />Live</span>
      </div>

      {/* Service cards */}
      <div className="svc-grid">
        <article className="svc">
          <header className="svc__head">
            <span className="svc__icon"><Icon name="rain" /></span>
            <div>
              <h3>{status?.weather.provider_name ?? "Weather API"}</h3>
              <span className="svc__sub">7-day forecast · external REST API</span>
            </div>
            <StatusDot ok={lastWeather ? lastWeather.status === "success" : null} />
          </header>
          <dl className="svc__rows">
            <div><dt>Endpoint</dt><dd><code>{status?.weather.endpoint ?? "—"}</code></dd></div>
            <div><dt>API key</dt><dd><code>{status?.weather.api_key_masked ?? "not configured"}</code></dd></div>
            <div><dt>Last call</dt><dd>{lastWeather ? `HTTP ${lastWeather.http_status ?? "—"} · ${lastWeather.latency_ms} ms · ${timeAgo(lastWeather.created_at)}` : "No calls yet"}</dd></div>
            <div><dt>Success</dt><dd>{weatherCalls.length ? `${weatherOkCount}/${weatherCalls.length} calls · avg ${avgLatency} ms` : "—"}</dd></div>
          </dl>
          {lastWeather && lastWeather.status !== "success" && lastWeather.http_status === 401 && (
            <p className="svc__hint">
              HTTP 401: the key is valid but One Call 3.0 isn't active yet. Subscribe to “One Call by Call” in your OpenWeather account.
            </p>
          )}
        </article>

        <article className="svc">
          <header className="svc__head">
            <span className="svc__icon"><Icon name="message" /></span>
            <div>
              <h3>{status?.sms.service ?? "Amazon SNS"}</h3>
              <span className="svc__sub">SMS irrigation alerts</span>
            </div>
            <StatusDot ok={lastSms ? lastSms.status === "sent" : status ? status.sms.recipients.length > 0 || status.sms.topic_configured : null} />
          </header>
          <dl className="svc__rows">
            <div><dt>Mode</dt><dd>{status?.sms.mode === "aws" ? "Live (AWS)" : "Simulated (in-memory SNS)"}</dd></div>
            <div><dt>Recipients</dt><dd><code>{status?.sms.recipients.length ? status.sms.recipients.join(", ") : "—"}</code></dd></div>
            <div><dt>Topic</dt><dd><code>{status?.sms.topic_name ?? "—"}</code></dd></div>
            <div><dt>Cooldown</dt><dd>{status ? `${status.sms.cooldown_minutes} min per zone` : "—"}</dd></div>
          </dl>
        </article>

        <article className="svc">
          <header className="svc__head">
            <span className="svc__icon"><Icon name="mail" /></span>
            <div>
              <h3>{status?.email.service ?? "Email"}</h3>
              <span className="svc__sub">Email alerts to registered subscribers</span>
            </div>
            <StatusDot ok={status ? status.email.mode === "smtp" : null} />
          </header>
          <dl className="svc__rows">
            <div><dt>Mode</dt><dd>{status?.email.mode === "smtp" ? "Live (SMTP)" : "Simulated"}</dd></div>
            <div><dt>Sender</dt><dd><code>{status?.email.sender ?? "—"}</code></dd></div>
            <div><dt>Subscribers</dt><dd>{status?.email.subscribers ?? "—"}</dd></div>
          </dl>
        </article>

        <article className="svc">
          <header className="svc__head">
            <span className="svc__icon"><Icon name="server" /></span>
            <div>
              <h3>Sensor ingest API</h3>
              <span className="svc__sub">API Gateway → Lambda → {status?.storage.service ?? "DynamoDB"}</span>
            </div>
            <StatusDot ok={sensorCalls.length ? true : null} />
          </header>
          <dl className="svc__rows">
            <div><dt>Endpoint</dt><dd><code>POST /zones/{"{zone_id}"}/readings</code></dd></div>
            <div><dt>Last reading</dt><dd>{sensorCalls[0] ? timeAgo(sensorCalls[0].created_at) : "—"}</dd></div>
            <div><dt>Recent</dt><dd>{sensorCalls.length} readings in log</dd></div>
            <div><dt>Region</dt><dd><code>{status?.region ?? "—"}</code></dd></div>
          </dl>
        </article>
      </div>

      <div className="int-grid">
        {/* Activity log */}
        <section className="panel">
          <div className="panel__head">
            <h2 className="section-title">API activity</h2>
            <div className="filter-tabs filter-tabs--compact">
              {([["all", "All"], ["weather", `Weather API · ${weatherCalls.length}`], ["sensor", "Sensors"]] as const).map(([id, label]) => (
                <button
                  key={id}
                  className={`filter-tab${filter === id ? " filter-tab--active" : ""}`}
                  onClick={() => setFilter(id)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          <div className="log">
            {apiLog.length === 0 && <div className="log__empty">No API traffic yet.</div>}
            {apiLog.map((e) => (
              <div key={e.event_id} className={`log__row${e.kind === "weather" ? " log__row--external" : ""}`}>
                <span className={`log__dir log__dir--${e.direction}`} title={e.direction}>
                  <Icon name={e.direction === "outbound" ? "arrow-out" : "arrow-in"} size={13} />
                </span>
                <span className="log__time">{clockTime(e.created_at)}</span>
                <div className="log__main">
                  <span className="log__provider">{e.provider}</span>
                  <code className="log__endpoint"><b>{e.method}</b> {e.endpoint}</code>
                  {e.kind === "sensor" && <span className="log__summary">{e.summary}</span>}
                </div>
                <span className={`http http--${e.status === "success" ? "ok" : "err"}`}>{e.http_status ?? "ERR"}</span>
                <span className="log__latency">{e.latency_ms !== undefined ? `${e.latency_ms} ms` : ""}</span>
              </div>
            ))}
          </div>
        </section>

        {/* SMS outbox */}
        <section className="phone">
          <div className="phone__notch" />
          <div className="phone__head">
            <span className="phone__avatar"><Icon name="sprout" size={16} /></span>
            <div>
              <strong>AgriIoT</strong>
              <span>SMS via Amazon SNS</span>
            </div>
          </div>
          <div className="phone__body">
            {smsLog.length === 0 && (
              <p className="phone__empty">No SMS sent yet. Alerts appear here the moment a zone needs irrigation.</p>
            )}
            {[...smsLog].reverse().map((e) => (
              <div key={e.event_id} className="sms">
                <div className={`sms__bubble${e.status !== "sent" ? " sms__bubble--failed" : ""}`}>
                  {e.message}
                </div>
                <span className="sms__meta">
                  {clockTime(e.created_at)} · to {e.target}
                  {e.status === "sent"
                    ? e.delivery === "mock" ? " · simulated" : ` · SNS ${e.message_id?.slice(0, 8)}…`
                    : ` · failed (${e.error ?? "error"})`}
                </span>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
};
