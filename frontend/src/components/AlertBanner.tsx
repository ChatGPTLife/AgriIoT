import type { CSSProperties, FC } from "react";
import type { Alert } from "../types";
import { Icon } from "./Icon";

interface Props {
  alert: Alert;
  onAcknowledge: (id: string) => void;
}

const URGENCY_COLOR: Record<string, string> = {
  HIGH: "var(--c-alert)",
  MEDIUM: "var(--c-urgency-med)",
  LOW: "var(--c-urgency-low)",
  NONE: "var(--text-muted)",
};

function timeSince(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export const AlertBanner: FC<Props> = ({ alert, onAcknowledge }) => {
  const color = URGENCY_COLOR[alert.urgency] ?? URGENCY_COLOR.NONE;

  return (
    <div className="alert-banner" style={{ "--urgency": color } as CSSProperties}>
      <div className="alert-banner__left">
        <span className="alert-banner__urgency-dot" />
        <div className="alert-banner__body">
          <div className="alert-banner__title">
            <strong>{alert.zone_name}</strong>
            <span className="alert-banner__urgency-label">{alert.urgency}</span>
            {alert.trigger === "manual" && <span className="alert-banner__manual">Manual</span>}
          </div>
          <p className="alert-banner__reason">{alert.reason}</p>
          <div className="alert-banner__stats">
            <span className="alert-banner__stat"><Icon name="droplet" size={12} />{alert.soil_moisture.toFixed(1)}% moisture</span>
            <span className="alert-banner__stat"><Icon name="activity" size={12} />Threshold {alert.threshold.toFixed(1)}%</span>
            <span className="alert-banner__stat"><Icon name="rain" size={12} />{alert.expected_rainfall_mm.toFixed(1)} mm expected</span>
            <span className="alert-banner__time">{timeSince(alert.created_at)}</span>
          </div>
        </div>
      </div>
      {alert.status === "active" && (
        <button
          className="alert-banner__ack-btn"
          onClick={() => onAcknowledge(alert.alert_id)}
          id={`ack-alert-${alert.alert_id}`}
        >
          <Icon name="check" size={14} />
          Acknowledge
        </button>
      )}
      {alert.status === "acknowledged" && (
        <span className="alert-banner__acked"><Icon name="check" size={14} />Acknowledged</span>
      )}
    </div>
  );
};
