"""
OpenWeatherMap One Call API 3.0 integration.

Fetches daily forecasts for a given lat/lon and returns a list of
ForecastDay objects ready to be cached in DynamoDB.

API reference: https://openweathermap.org/api/one-call-3
Requires a paid (or free-tier) One Call API 3.0 subscription.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

import requests

from src.models.weather import ForecastDay
from src.services.activity import mask_secret, tracked_request
from src.utils.config import AppConfig, get_config
from src.utils.errors import (
    ConfigurationError,
    ExternalServiceError,
    ForecastIncompleteError,
    RateLimitedError,
    UpstreamTimeoutError,
)
from src.utils.ids import utc_now_iso

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.openweathermap.org/data/3.0/onecall"

# Mapping from OWM weather condition IDs to a short human-readable string.
# Only the most agronomically relevant groups are listed; anything else
# falls back to "unknown".
_CONDITION_MAP: Dict[int, str] = {
    # Thunderstorm
    **{k: "thunderstorm" for k in range(200, 300)},
    # Drizzle
    **{k: "drizzle" for k in range(300, 400)},
    # Rain
    **{k: "rain" for k in range(500, 600)},
    # Snow
    **{k: "snow" for k in range(600, 700)},
    # Clear
    800: "clear",
    # Clouds
    **{k: "cloudy" for k in range(801, 900)},
}


def _condition_label(weather_list: List[Dict[str, Any]]) -> str:
    if not weather_list:
        return "unknown"
    icon_id = weather_list[0].get("id", 0)
    # Try exact match, then hundreds-group fallback
    return _CONDITION_MAP.get(icon_id, _CONDITION_MAP.get((icon_id // 100) * 100, "unknown"))


def fetch_forecast(
    zone_id: str,
    latitude: float,
    longitude: float,
    days: int | None = None,
    config: AppConfig | None = None,
) -> List[ForecastDay]:
    """
    Call the OpenWeatherMap One Call API 3.0 and return a list of
    ForecastDay objects (one per day, up to `days` or config.forecast_days).

    Raises
    ------
    ConfigurationError       if OPENWEATHER_API_KEY is not set.
    UpstreamTimeoutError     if the HTTP request times out.
    RateLimitedError         if OWM returns 429.
    ExternalServiceError     for any other non-2xx response.
    ForecastIncompleteError  if fewer than `days` days are returned.
    """
    config = config or get_config()
    target_days = days or config.forecast_days

    if not config.openweather_api_key:
        raise ConfigurationError(
            "OPENWEATHER_API_KEY is not set. "
            "Set it in your .env file or as a Lambda environment variable."
        )

    params = {
        "lat": latitude,
        "lon": longitude,
        "exclude": "current,minutely,hourly,alerts",
        "units": "metric",
        "appid": config.openweather_api_key,
    }

    logger.info(
        "Fetching OpenWeatherMap forecast for zone=%s lat=%.4f lon=%.4f days=%d",
        zone_id,
        latitude,
        longitude,
        target_days,
    )

    try:
        resp = tracked_request(
            "GET",
            _BASE_URL,
            provider="OpenWeatherMap One Call 3.0",
            api_key=config.openweather_api_key,
            zone_id=zone_id,
            query_hint=f"lat={latitude:.4f}&lon={longitude:.4f}&units=metric&appid={mask_secret(config.openweather_api_key)}",
            params=params,
            timeout=config.weather_http_timeout_seconds,
        )
    except requests.Timeout as exc:
        raise UpstreamTimeoutError(
            "OpenWeatherMap API timed out. Please try again later."
        ) from exc
    except requests.RequestException as exc:
        raise ExternalServiceError(
            "Failed to reach OpenWeatherMap API. Please try again later."
        ) from exc

    if resp.status_code == 401:
        raise ConfigurationError(
            "OpenWeatherMap API key is invalid or missing the One Call 3.0 subscription."
        )
    if resp.status_code == 429:
        raise RateLimitedError(
            "OpenWeatherMap API rate limit reached. Please wait before retrying."
        )
    if not resp.ok:
        logger.error(
            "OpenWeatherMap returned %s: %s", resp.status_code, resp.text[:200]
        )
        raise ExternalServiceError(
            f"OpenWeatherMap API returned an unexpected error (HTTP {resp.status_code})."
        )

    data = resp.json()
    daily: List[Dict[str, Any]] = data.get("daily", [])

    fetched_at = utc_now_iso()
    result: List[ForecastDay] = []

    for day_data in daily[:target_days]:
        dt_epoch: int = day_data.get("dt", 0)
        from datetime import datetime, timezone
        forecast_date = datetime.fromtimestamp(dt_epoch, tz=timezone.utc).strftime("%Y-%m-%d")

        temp = day_data.get("temp", {})
        rain_mm = day_data.get("rain", 0.0) or 0.0
        pop = day_data.get("pop", 0.0) or 0.0  # probability of precipitation (0-1)

        result.append(
            ForecastDay(
                zone_id=zone_id,
                forecast_date=forecast_date,
                fetched_at=fetched_at,
                temperature_min=float(temp.get("min", 0.0)),
                temperature_max=float(temp.get("max", 0.0)),
                humidity=float(day_data.get("humidity", 0.0)),
                precipitation_mm=float(rain_mm),
                precipitation_probability=float(pop * 100),  # convert 0-1 → 0-100
                condition=_condition_label(day_data.get("weather", [])),
                provider="openweather",
            )
        )

    if len(result) < target_days:
        raise ForecastIncompleteError(
            f"OpenWeatherMap returned only {len(result)} forecast day(s); "
            f"{target_days} are required."
        )

    logger.info(
        "OpenWeatherMap: received %d forecast days for zone=%s", len(result), zone_id
    )
    return result
