import type { FC } from "react";
import type { Zone, IrrigationDecision } from "../types";
import { Icon } from "./Icon";

interface Props {
  zone: Zone;
  decision: IrrigationDecision | null;
  onInspect?: (zone: Zone) => void;
}

const REC_CONFIG = {
  NO_IRRIGATION_NEEDED: {
    label: "Optimal",
    color: "var(--c-ok)",
    badge: "badge-ok",
    glow: "glow-ok",
  },
  WAIT_FOR_RAIN: {
    label: "Rain expected",
    color: "var(--c-wait)",
    badge: "badge-wait",
    glow: "glow-wait",
  },
  IRRIGATION_REQUIRED: {
    label: "Irrigate",
    color: "var(--c-alert)",
    badge: "badge-alert",
    glow: "glow-alert",
  },
};

const URGENCY_LABEL: Record<string, string> = {
  NONE: "",
  LOW: " · Low",
  MEDIUM: " · Medium",
  HIGH: " · High",
};

function MoistureBar({ value, threshold }: { value: number; threshold: number }) {
  const pct = Math.min(100, Math.max(0, value));
  const isLow = value < threshold;
  return (
    <div className="moisture-bar-wrap">
      <div
        className="moisture-bar-fill"
        style={{
          width: `${pct}%`,
          background: isLow
            ? "linear-gradient(90deg, var(--c-alert), var(--c-alert-light))"
            : "linear-gradient(90deg, var(--c-ok), var(--c-ok-light))",
        }}
      />
      <div
        className="moisture-bar-threshold"
        style={{ left: `${threshold}%` }}
        title={`Threshold: ${threshold}%`}
      />
    </div>
  );
}

export const ZoneCard: FC<Props> = ({ zone, decision, onInspect }) => {
  const rec = decision?.recommendation ?? "NO_IRRIGATION_NEEDED";
  const cfg = REC_CONFIG[rec];
  const urgency = decision?.urgency ?? "NONE";

  return (
    <div className={`zone-card ${cfg.glow}`} onClick={() => onInspect?.(zone)}>
      {/* Header */}
      <div className="zone-card__header">
        <div>
          <h3 className="zone-card__name">{zone.name}</h3>
          <span className="zone-card__meta">
            {zone.crop_type} · {zone.soil_type}
          </span>
        </div>
        <span className={`badge ${cfg.badge}`}>
          {cfg.label}{URGENCY_LABEL[urgency]}
        </span>
      </div>

      {/* Moisture */}
      <div className="zone-card__moisture-section">
        <div className="zone-card__moisture-label">
          <span>Soil Moisture</span>
          <span className="zone-card__moisture-value">
            {decision?.soil_moisture !== undefined
              ? `${decision.soil_moisture.toFixed(1)}%`
              : "—"}
          </span>
        </div>
        <MoistureBar
          value={decision?.soil_moisture ?? zone.moisture_threshold}
          threshold={zone.moisture_threshold}
        />
        <div className="zone-card__moisture-range">
          <span>0%</span>
          <span>Threshold: {zone.moisture_threshold}%</span>
          <span>100%</span>
        </div>
      </div>

      {/* Stats row */}
      <div className="zone-card__stats">
        <div className="zone-card__stat">
          <span className="zone-card__stat-label"><Icon name="thermometer" size={12} />Temp</span>
          <span className="zone-card__stat-value">
            {decision?.temperature !== undefined
              ? `${decision.temperature.toFixed(1)}°C`
              : "—"}
          </span>
        </div>
        <div className="zone-card__stat">
          <span className="zone-card__stat-label"><Icon name="droplet" size={12} />Humidity</span>
          <span className="zone-card__stat-value">
            {decision?.humidity !== undefined
              ? `${decision.humidity.toFixed(0)}%`
              : "—"}
          </span>
        </div>
        <div className="zone-card__stat">
          <span className="zone-card__stat-label"><Icon name="rain" size={12} />Rain (2d)</span>
          <span className="zone-card__stat-value">
            {decision?.forecast_rainfall_mm !== undefined
              ? `${decision.forecast_rainfall_mm.toFixed(1)} mm`
              : "—"}
          </span>
        </div>
      </div>

      {/* Reason */}
      {decision?.reason && (
        <p className="zone-card__reason">{decision.reason}</p>
      )}

      {!zone.enabled && (
        <div className="zone-card__disabled-banner">Zone Disabled</div>
      )}
    </div>
  );
};
