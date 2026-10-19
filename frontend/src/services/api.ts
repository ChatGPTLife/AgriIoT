// API service layer — all typed wrappers around the backend REST API.
// Set VITE_API_BASE_URL in .env (or .env.production) to point at your
// deployed API Gateway or local dev server.

const BASE = import.meta.env.VITE_API_BASE_URL ?? "";

export interface Zone {
  zone_id: string;
  name: string;
  latitude: number;
  longitude: number;
  crop_type: string;
  soil_type: string;
  moisture_threshold: number;
  target_moisture: number;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface ForecastDay {
  zone_id: string;
  forecast_date: string;
  temperature_min: number;
  temperature_max: number;
  humidity: number;
  precipitation_mm: number;
  precipitation_probability: number;
  condition: string;
  provider: string;
  fetched_at?: string;
}

export interface IrrigationDecision {
  zone_id: string;
  evaluated_at: string;
  recommendation: "NO_IRRIGATION_NEEDED" | "WAIT_FOR_RAIN" | "IRRIGATION_REQUIRED";
  urgency: "NONE" | "LOW" | "MEDIUM" | "HIGH";
  reason: string;
  soil_moisture: number;
  moisture_threshold: number;
  target_moisture: number;
  temperature?: number;
  humidity?: number;
  forecast_rainfall_mm?: number;
  rain_probability?: number;
  reading_id?: string;
}

export interface Alert {
  alert_id: string;
  zone_id: string;
  zone_name: string;
  created_at: string;
  status: "active" | "acknowledged";
  urgency: "NONE" | "LOW" | "MEDIUM" | "HIGH";
  reason: string;
  soil_moisture: number;
  threshold: number;
  expected_rainfall_mm: number;
  rain_probability: number;
  acknowledged_at?: string;
  trigger?: "automatic" | "manual";
  recommendation?: IrrigationDecision["recommendation"];
}

export interface SensorReadingPayload {
  soil_moisture: number;
  temperature: number;
  humidity: number;
  device_id?: string;
}

export interface IngestResponse {
  success: boolean;
  decision: IrrigationDecision;
  reading_id: string;
  alert_id: string | null;
}

export interface SensorReading {
  reading_id: string;
  zone_id: string;
  device_id?: string;
  soil_moisture: number;
  temperature: number;
  humidity: number;
  timestamp: string;
}

export interface SystemStatus {
  environment: string;
  region: string;
  weather: {
    provider: string;
    provider_name: string;
    endpoint: string | null;
    api_key_configured: boolean;
    api_key_masked: string | null;
    forecast_days: number;
    fallback: string | null;
  };
  sms: {
    service: string;
    mode: "aws" | "mock";
    topic_configured: boolean;
    topic_name: string | null;
    recipients: string[];
    cooldown_minutes: number;
  };
  email: {
    service: string;
    mode: "smtp" | "mock";
    sender: string | null;
    subscribers: number;
  };
  storage: { service: string };
}

export interface Subscriber {
  subscriber_id: string;
  name: string;
  email: string; // masked by the API
  zone_ids: string[]; // ["*"] = all zones
  active: boolean;
  created_at: string;
}

export interface EmailDelivery {
  to: string;
  status: "sent" | "simulated" | "failed";
  error: string | null;
  event_id: string;
}

export interface ActivityEvent {
  event_id: string;
  stream: "weather" | "sensor" | "sms" | "email";
  created_at: string;
  kind: "weather" | "sensor" | "sms" | "alert" | "welcome";
  subject?: string;
  status: string;
  zone_id?: string;
  // api stream
  direction?: "inbound" | "outbound";
  provider?: string;
  method?: string;
  endpoint?: string;
  api_key_masked?: string | null;
  http_status?: number | null;
  latency_ms?: number;
  summary?: string;
  // sms stream
  target?: string;
  target_type?: "topic" | "phone";
  message?: string;
  delivery?: "aws" | "mock" | "smtp";
  message_id?: string | null;
  error?: string | null;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const json = await resp.json();
  if (!resp.ok || json.success === false) {
    const msg = json?.error?.message ?? `HTTP ${resp.status}`;
    throw new Error(msg);
  }
  return json as T;
}

// ── Zones ──────────────────────────────────────────────────────────────────
export const api = {
  zones: {
    list: () => request<{ zones: Zone[] }>("/zones"),
    get: (id: string) => request<{ zone: Zone }>(`/zones/${id}`),
    create: (body: Partial<Zone>) =>
      request<{ zone: Zone }>("/zones", { method: "POST", body: JSON.stringify(body) }),
    update: (id: string, body: Partial<Zone>) =>
      request<{ zone: Zone }>(`/zones/${id}`, { method: "PUT", body: JSON.stringify(body) }),
    delete: (id: string) =>
      request<{ deleted: string }>(`/zones/${id}`, { method: "DELETE" }),
  },

  // ── Weather ───────────────────────────────────────────────────────────────
  weather: {
    get: (zone_id: string) =>
      request<{ forecast: ForecastDay[]; days: number }>(`/zones/${zone_id}/weather`),
    refresh: (zone_id: string) =>
      request<{ refreshed: number; forecast: ForecastDay[] }>(
        `/zones/${zone_id}/weather/refresh`,
        { method: "POST" }
      ),
  },

  // ── Irrigation ────────────────────────────────────────────────────────────
  irrigation: {
    ingest: (zone_id: string, payload: SensorReadingPayload) =>
      request<IngestResponse>(`/zones/${zone_id}/readings`, {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    latestDecision: (zone_id: string) =>
      request<{ zone_id: string; decision: IrrigationDecision | null }>(
        `/zones/${zone_id}/irrigation/latest`
      ),
    listDecisions: (params?: { zone_id?: string; limit?: number }) => {
      const qs = new URLSearchParams(
        Object.entries(params ?? {})
          .filter(([, v]) => v !== undefined)
          .map(([k, v]) => [k, String(v)])
      ).toString();
      return request<{ decisions: IrrigationDecision[]; count: number }>(
        `/irrigation/decisions${qs ? "?" + qs : ""}`
      );
    },
  },

  // ── Sensor readings ───────────────────────────────────────────────────────
  readings: {
    list: (zone_id: string, hours = 72) =>
      request<{ readings: SensorReading[]; count: number }>(`/zones/${zone_id}/readings?hours=${hours}`),
  },

  // ── System / integrations ─────────────────────────────────────────────────
  system: {
    status: () => request<SystemStatus>("/system/status"),
    activity: (stream: "weather" | "sensor" | "sms" | "email", limit = 50) =>
      request<{ events: ActivityEvent[]; count: number }>(`/system/activity?stream=${stream}&limit=${limit}`),
  },

  // ── Email subscribers ─────────────────────────────────────────────────────
  subscribers: {
    list: () => request<{ subscribers: Subscriber[]; count: number }>("/subscribers"),
    create: (body: { name: string; email: string; zone_ids?: string[] }) =>
      request<{ subscriber: Subscriber; welcome_email: EmailDelivery }>("/subscribers", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    delete: (id: string) => request<{ deleted: string }>(`/subscribers/${id}`, { method: "DELETE" }),
  },

  // ── Alerts ────────────────────────────────────────────────────────────────
  alerts: {
    trigger: (zone_id: string) =>
      request<{
        alert: Alert & { delivery: { sms_message_id: string | null; sms_mode: string; emails: EmailDelivery[] } };
        decision: IrrigationDecision;
      }>(`/zones/${zone_id}/alerts/trigger`, { method: "POST" }),
    list: (params?: { status?: string; zone_id?: string }) => {
      const qs = new URLSearchParams(
        Object.entries(params ?? {})
          .filter(([, v]) => v !== undefined)
          .map(([k, v]) => [k, String(v)])
      ).toString();
      return request<{ alerts: Alert[]; count: number }>(
        `/alerts${qs ? "?" + qs : ""}`
      );
    },
    get: (id: string) => request<{ alert: Alert }>(`/alerts/${id}`),
    acknowledge: (id: string) =>
      request<{ alert: Alert }>(`/alerts/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: "acknowledged" }),
      }),
  },
};
