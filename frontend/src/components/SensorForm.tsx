import { useState, type FC } from "react";
import { api } from "../services/api";
import type { IngestResponse } from "../types";

interface Props {
  zoneId: string;
  zoneName: string;
  onSuccess?: (resp: IngestResponse) => void;
}

export const SensorForm: FC<Props> = ({ zoneId, zoneName, onSuccess }) => {
  const [moisture, setMoisture] = useState("35");
  const [temperature, setTemperature] = useState("28");
  const [humidity, setHumidity] = useState("55");
  const [deviceId, setDeviceId] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<IngestResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const resp = await api.irrigation.ingest(zoneId, {
        soil_moisture: parseFloat(moisture),
        temperature: parseFloat(temperature),
        humidity: parseFloat(humidity),
        device_id: deviceId || undefined,
      });
      setResult(resp);
      onSuccess?.(resp);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="sensor-form">
      <h3 className="sensor-form__title">Submit Reading — {zoneName}</h3>
      <form onSubmit={handleSubmit} className="sensor-form__fields">
        <label className="sensor-form__label">
          Soil Moisture (%)
          <input
            id={`moisture-${zoneId}`}
            type="number"
            min="0"
            max="100"
            step="0.1"
            value={moisture}
            onChange={(e) => setMoisture(e.target.value)}
            className="sensor-form__input"
            required
          />
        </label>
        <label className="sensor-form__label">
          Temperature (°C)
          <input
            id={`temperature-${zoneId}`}
            type="number"
            min="-40"
            max="70"
            step="0.1"
            value={temperature}
            onChange={(e) => setTemperature(e.target.value)}
            className="sensor-form__input"
            required
          />
        </label>
        <label className="sensor-form__label">
          Humidity (%)
          <input
            id={`humidity-${zoneId}`}
            type="number"
            min="0"
            max="100"
            step="1"
            value={humidity}
            onChange={(e) => setHumidity(e.target.value)}
            className="sensor-form__input"
            required
          />
        </label>
        <label className="sensor-form__label">
          Device ID (optional)
          <input
            id={`device-id-${zoneId}`}
            type="text"
            value={deviceId}
            onChange={(e) => setDeviceId(e.target.value)}
            className="sensor-form__input"
            placeholder="sensor-001"
          />
        </label>
        <button
          type="submit"
          disabled={loading}
          className="sensor-form__submit"
          id={`submit-reading-${zoneId}`}
        >
          {loading ? "Submitting…" : "Submit Reading"}
        </button>
      </form>

      {result && (
        <div className={`sensor-form__result sensor-form__result--${result.decision.recommendation.toLowerCase().replace(/_/g, "-")}`}>
          <strong>Decision:</strong> {result.decision.recommendation} ({result.decision.urgency})
          <p>{result.decision.reason}</p>
          {result.alert_id && (
            <p className="sensor-form__alert-note">Alert created · {result.alert_id}</p>
          )}
        </div>
      )}
      {error && <p className="sensor-form__error">{error}</p>}
    </div>
  );
};
