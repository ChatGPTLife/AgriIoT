import type { FC } from "react";
import type { ForecastDay, IrrigationDecision, SensorReading, SystemStatus, Zone } from "../types";
import { CONDITION_ICONS } from "./WeatherForecast";
import { MoistureChart } from "./MoistureChart";
import { Icon } from "./Icon";
import { clockTime, shortDay, timeAgo } from "../utils/time";

interface Props {
  zones: Zone[];
  zone: Zone;
  onSelectZone: (id: string) => void;
  forecast: ForecastDay[];
  readings: SensorReading[];
  decision: IrrigationDecision | null;
  status: SystemStatus | null;
  onTrigger: () => void;
  triggering: boolean;
}

const REC_TEXT: Record<string, string> = {
  NO_IRRIGATION_NEEDED: "Optimal",
  WAIT_FOR_RAIN: "Rain expected",
  IRRIGATION_REQUIRED: "Irrigate now",
};

function conditionLabel(c?: string | null): string {
  if (!c) return "No forecast";
  const s = c.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// One reading per 3-hour slot over the last 24h, newest last.
function hourlySamples(readings: SensorReading[]): SensorReading[] {
  if (!readings.length) return [];
  const last = new Date(readings[readings.length - 1].timestamp).getTime();
  const out: SensorReading[] = [];
  for (let k = 7; k >= 0; k--) {
    const target = last - k * 3 * 3600_000;
    let best = readings[0];
    for (const r of readings) {
      if (Math.abs(new Date(r.timestamp).getTime() - target) < Math.abs(new Date(best.timestamp).getTime() - target)) best = r;
    }
    if (!out.includes(best)) out.push(best);
  }
  return out;
}

export const WeatherHero: FC<Props> = ({
  zones, zone, onSelectZone, forecast, readings, decision, status, onTrigger, triggering,
}) => {
  const latest = readings[readings.length - 1];
  const today = forecast[0];
  const rain2d = forecast.slice(0, 2).reduce((s, d) => s + d.precipitation_mm, 0);
  const rainProb = forecast.slice(0, 2).reduce((m, d) => Math.max(m, d.precipitation_probability), 0);
  const fetchedAt = today?.fetched_at;

  return (
    <section className="wx">
      <div className="wx__head">
        <h2 className="wx__title">Field conditions</h2>
        <div className="segmented" role="tablist">
          {zones.map((z) => (
            <button
              key={z.zone_id}
              role="tab"
              aria-selected={z.zone_id === zone.zone_id}
              className={`segmented__item${z.zone_id === zone.zone_id ? " segmented__item--active" : ""}`}
              onClick={() => onSelectZone(z.zone_id)}
            >
              {z.name}
            </button>
          ))}
        </div>
        <div className="api-chip">
          <Icon name="key" size={13} />
          <span>{status?.weather.provider_name ?? "Weather API"}</span>
          {status?.weather.api_key_masked && <code>{status.weather.api_key_masked}</code>}
          {fetchedAt && <span className="api-chip__state">updated {timeAgo(fetchedAt)}</span>}
        </div>
      </div>

      {/* Day pills */}
      <div className="wx__days">
        {forecast.length ? (
          forecast.map((d, i) => (
            <div key={d.forecast_date} className={`day-pill${i === 0 ? " day-pill--active" : ""}`} title={`${d.precipitation_mm.toFixed(1)} mm · ${Math.round(d.precipitation_probability)}% chance`}>
              <span className="day-pill__day">{shortDay(d.forecast_date, i)}</span>
              <span className="day-pill__temp">{Math.round(d.temperature_max)}<sup>°</sup></span>
              <span className="day-pill__icon">{CONDITION_ICONS[d.condition ?? "unknown"] ?? "🌡"}</span>
            </div>
          ))
        ) : (
          <div className="wx__notice">
            <Icon name="refresh" size={14} />
            Fetching the 7-day forecast…
          </div>
        )}
      </div>

      <div className="wx__grid">
        {/* Now card */}
        <div className="wx__now">
          <div className="wx__sky">
            <span className="wx__sky-time">
              {latest ? <>Sensor {latest.device_id ?? ""} · {clockTime(latest.timestamp)}</> : "No readings yet"}
            </span>
            <span className="wx__sky-temp">{latest ? Math.round(latest.temperature) : "—"}°</span>
            <span className="wx__sky-cond">
              <strong>{conditionLabel(today?.condition)}</strong>
              <span>{today ? `High ${Math.round(today.temperature_max)}° · Low ${Math.round(today.temperature_min)}°` : `${zone.crop_type} · ${zone.soil_type}`}</span>
            </span>
          </div>
          <div className="wx__tiles">
            <div className="tile">
              <span className="tile__label"><Icon name="droplet" size={13} />Soil moisture</span>
              <span className="tile__value">{latest ? `${latest.soil_moisture.toFixed(1)}%` : "—"}</span>
            </div>
            <div className="tile">
              <span className="tile__label"><Icon name="activity" size={13} />Threshold</span>
              <span className="tile__value">{zone.moisture_threshold}%</span>
            </div>
            <div className="tile">
              <span className="tile__label"><Icon name="wind" size={13} />Humidity</span>
              <span className="tile__value">{latest ? `${Math.round(latest.humidity)}%` : "—"}</span>
            </div>
            <div className="tile">
              <span className="tile__label"><Icon name="rain" size={13} />Rain · 2 days</span>
              <span className="tile__value">{forecast.length ? `${rain2d.toFixed(1)} mm` : "—"}</span>
            </div>
            <div className="tile">
              <span className="tile__label"><Icon name="rain" size={13} />Rain chance</span>
              <span className="tile__value">{forecast.length ? `${Math.round(rainProb)}%` : "—"}</span>
            </div>
            <div className={`tile tile--${(decision?.recommendation ?? "none").toLowerCase().replace(/_/g, "-")}`}>
              <span className="tile__label"><Icon name="sprout" size={13} />Decision</span>
              <span className="tile__value">{decision ? REC_TEXT[decision.recommendation] : "—"}</span>
            </div>
          </div>
          <button className="btn-primary wx__trigger" onClick={onTrigger} disabled={triggering} id="trigger-alert">
            <Icon name="zap" size={14} />
            {triggering ? "Sending alert…" : `Trigger alert for ${zone.name}`}
          </button>
          <span className="wx__trigger-hint">Sends the SMS and emails all subscribers now</span>
        </div>

        {/* Trend panel */}
        <div className="wx__panel">
          <div className="wx__panel-head">
            <h3>Soil moisture · last 72 hours</h3>
            <span className="wx__panel-meta">
              {readings.length} readings{fetchedAt ? ` · forecast fetched ${timeAgo(fetchedAt)}` : ""}
            </span>
          </div>
          <MoistureChart readings={readings} threshold={zone.moisture_threshold} target={zone.target_moisture} />
          <div className="wx__hourly">
            {hourlySamples(readings).map((r) => (
              <div key={r.reading_id} className="hour-tile">
                <span className="hour-tile__time">{clockTime(r.timestamp)}</span>
                <span className={`hour-tile__moist${r.soil_moisture < zone.moisture_threshold ? " hour-tile__moist--low" : ""}`}>
                  {r.soil_moisture.toFixed(0)}%
                </span>
                <span className="hour-tile__temp">{Math.round(r.temperature)}°</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
};
