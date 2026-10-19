"""
Tomorrow.io Timelines API integration.

Fetches daily weather timelines for a given lat/lon and normalises the
result into the same List[ForecastDay] shape returned by openweather.py,
so the rest of the system is provider-agnostic.

API reference: https://docs.tomorrow.io/reference/post-timelines
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

import requests

from src.models.weather import ForecastDay
from src.services.activity import tracked_request
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

_BASE_URL = "https://api.tomorrow.io/v4/timelines"

# Tomorrow.io weather codes → human-readable condition string.
# Reference: https://docs.tomorrow.io/reference/data-layers-weather-codes
_WEATHER_CODE_MAP: Dict[int, str] = {
    1000: "clear",
    1001: "cloudy",
    1100: "mostly_clear",
    1101: "partly_cloudy",
    1102: "mostly_cloudy",
    2000: "fog",
    2100: "light_fog",
    3000: "light_wind",
    3001: "wind",
    3002: "strong_wind",
    4000: "drizzle",
    4001: "rain",
    4200: "light_rain",
    4201: "heavy_rain",
    5000: "snow",
    5001: "flurries",
    5100: "light_snow",
    5101: "heavy_snow",
    6000: "freezing_drizzle",
    6001: "freezing_rain",
    6200: "light_freezing_rain",
    6201: "heavy_freezing_rain",
    7000: "ice_pellets",
    7101: "heavy_ice_pellets",
    7102: "light_ice_pellets",
    8000: "thunderstorm",
}

# Fields we request from the Timelines API.
_FIELDS = [
    "temperatureMin",
    "temperatureMax",
    "humidityAvg",
    "precipitationIntensityAvg",
    "precipitationProbability",
    "weatherCodeDay",
]


def fetch_forecast(
    zone_id: str,
    latitude: float,
    longitude: float,
    days: int | None = None,
    config: AppConfig | None = None,
) -> List[ForecastDay]:
    """
    Call the Tomorrow.io Timelines API and return a list of ForecastDay
    objects (one per day, up to `days` or config.forecast_days).

    Raises
    ------
    ConfigurationError       if TOMORROWIO_API_KEY is not set.
    UpstreamTimeoutError     if the HTTP request times out.
    RateLimitedError         if Tomorrow.io returns 429.
    ExternalServiceError     for any other non-2xx response.
    ForecastIncompleteError  if fewer than `days` days are returned.
    """
    config = config or get_config()
    target_days = days or config.forecast_days

    if not config.tomorrowio_api_key:
        raise ConfigurationError(
            "TOMORROWIO_API_KEY is not set. "
            "Set it in your .env file or as a Lambda environment variable."
        )

    payload: Dict[str, Any] = {
        "location": f"{latitude},{longitude}",
        "fields": _FIELDS,
        "units": "metric",
        "timesteps": ["1d"],
        "startTime": "nowDay",
        "endTime": f"nowDay+{target_days}d",
    }

    headers = {
        "apikey": config.tomorrowio_api_key,
        "Content-Type": "application/json",
    }

    logger.info(
        "Fetching Tomorrow.io forecast for zone=%s lat=%.4f lon=%.4f days=%d",
        zone_id,
        latitude,
        longitude,
        target_days,
    )

    try:
        resp = tracked_request(
            "POST",
            _BASE_URL,
            provider="Tomorrow.io Timelines v4",
            api_key=config.tomorrowio_api_key,
            zone_id=zone_id,
            query_hint=f"location={latitude:.4f},{longitude:.4f}&timesteps=1d",
            json=payload,
            headers=headers,
            timeout=config.weather_http_timeout_seconds,
        )
    except requests.Timeout as exc:
        raise UpstreamTimeoutError(
            "Tomorrow.io API timed out. Please try again later."
        ) from exc
    except requests.RequestException as exc:
        raise ExternalServiceError(
            "Failed to reach Tomorrow.io API. Please try again later."
        ) from exc

    if resp.status_code in (401, 403):
        raise ConfigurationError(
            "Tomorrow.io API key is invalid or lacks the required permissions."
        )
    if resp.status_code == 429:
        raise RateLimitedError(
            "Tomorrow.io API rate limit reached. Please wait before retrying."
        )
    if not resp.ok:
        logger.error(
            "Tomorrow.io returned %s: %s", resp.status_code, resp.text[:200]
        )
        raise ExternalServiceError(
            f"Tomorrow.io API returned an unexpected error (HTTP {resp.status_code})."
        )

    data = resp.json()
    # Navigate: data → timelines[0] → intervals
    try:
        intervals: List[Dict[str, Any]] = (
            data["data"]["timelines"][0]["intervals"]
        )
    except (KeyError, IndexError, TypeError) as exc:
        logger.error("Unexpected Tomorrow.io response shape: %s", str(data)[:300])
        raise ExternalServiceError(
            "Tomorrow.io returned an unexpected response format."
        ) from exc

    fetched_at = utc_now_iso()
    result: List[ForecastDay] = []

    for interval in intervals[:target_days]:
        start_time: str = interval.get("startTime", "")
        # startTime is ISO 8601, e.g. "2024-05-01T06:00:00Z"
        forecast_date = start_time[:10] if len(start_time) >= 10 else "unknown"

        values: Dict[str, Any] = interval.get("values", {})
        weather_code: int = int(values.get("weatherCodeDay", 0))

        # Tomorrow.io precipitationIntensityAvg is mm/h; multiply by 24 for daily total
        precip_intensity = float(values.get("precipitationIntensityAvg", 0.0) or 0.0)
        precip_mm = precip_intensity * 24.0

        result.append(
            ForecastDay(
                zone_id=zone_id,
                forecast_date=forecast_date,
                fetched_at=fetched_at,
                temperature_min=float(values.get("temperatureMin", 0.0)),
                temperature_max=float(values.get("temperatureMax", 0.0)),
                humidity=float(values.get("humidityAvg", 0.0)),
                precipitation_mm=precip_mm,
                precipitation_probability=float(
                    values.get("precipitationProbability", 0.0) or 0.0
                ),
                condition=_WEATHER_CODE_MAP.get(weather_code, "unknown"),
                provider="tomorrowio",
            )
        )

    if len(result) < target_days:
        raise ForecastIncompleteError(
            f"Tomorrow.io returned only {len(result)} forecast day(s); "
            f"{target_days} are required."
        )

    logger.info(
        "Tomorrow.io: received %d forecast days for zone=%s", len(result), zone_id
    )
    return result
