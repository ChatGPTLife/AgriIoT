import type { FC } from "react";
import type { ForecastDay } from "../types";

interface Props {
  forecast: ForecastDay[];
}

export const CONDITION_ICONS: Record<string, string> = {
  clear: "☀️",
  mostly_clear: "🌤",
  partly_cloudy: "⛅",
  mostly_cloudy: "🌥",
  cloudy: "☁️",
  drizzle: "🌦",
  light_rain: "🌦",
  rain: "🌧",
  heavy_rain: "⛈",
  thunderstorm: "⛈",
  snow: "❄️",
  light_snow: "🌨",
  heavy_snow: "❄️",
  fog: "🌫",
  light_fog: "🌫",
  wind: "💨",
  strong_wind: "🌬",
  unknown: "🌡",
};

function formatDate(dateStr: string): string {
  const d = new Date(dateStr + "T12:00:00Z");
  return d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
}

export const WeatherForecast: FC<Props> = ({ forecast }) => {
  if (!forecast.length) {
    return (
      <div className="forecast-empty">
        No forecast data. Trigger a weather refresh.
      </div>
    );
  }

  const maxRain = Math.max(...forecast.map((d) => d.precipitation_mm), 1);

  return (
    <div className="forecast-strip">
      {forecast.map((day) => {
        const icon = CONDITION_ICONS[day.condition] ?? "🌡";
        const barHeight = Math.max(4, (day.precipitation_mm / maxRain) * 48);
        return (
          <div key={day.forecast_date} className="forecast-day">
            <span className="forecast-day__date">{formatDate(day.forecast_date)}</span>
            <span className="forecast-day__icon">{icon}</span>
            <span className="forecast-day__temp">
              {Math.round(day.temperature_max)}° / {Math.round(day.temperature_min)}°
            </span>
            {/* Precipitation bar */}
            <div className="forecast-day__rain-wrap" title={`${day.precipitation_mm.toFixed(1)} mm`}>
              <div
                className="forecast-day__rain-bar"
                style={{ height: `${barHeight}px` }}
              />
            </div>
            <span className="forecast-day__rain-label">
              {day.precipitation_mm.toFixed(1)} mm
            </span>
            <span className="forecast-day__prob">
              {Math.round(day.precipitation_probability)}%
            </span>
          </div>
        );
      })}
    </div>
  );
};
