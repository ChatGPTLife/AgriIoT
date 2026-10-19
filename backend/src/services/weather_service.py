"""
Weather service.

Orchestrates: fetch from provider → validate completeness → cache in DynamoDB.
Called by the weather Lambda handler (on-demand refresh) and by the scheduled
EventBridge weather-refresh Lambda function.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from src.integrations.weather_provider import get_provider
from src.models.weather import ForecastDay
from src.repositories import weather as weather_repo
from src.repositories import zones as zones_repo
from src.utils.config import AppConfig, get_config
from src.utils.errors import WeatherUnavailableError, ZoneNotFoundError

logger = logging.getLogger(__name__)


def refresh_forecast(
    zone_id: str,
    config: AppConfig | None = None,
) -> List[ForecastDay]:
    """
    Fetch a fresh weather forecast for `zone_id`, validate it, persist
    it to the DynamoDB cache, and return the list of ForecastDay objects.

    Raises
    ------
    ZoneNotFoundError        if the zone does not exist in DynamoDB.
    ConfigurationError       if the provider API key is missing.
    ForecastIncompleteError  if the provider returns fewer days than required.
    ExternalServiceError     for any other provider-level failure.
    """
    config = config or get_config()

    # 1. Load zone to get lat/lon
    zone: Dict[str, Any] | None = zones_repo.get_zone(zone_id)
    if zone is None:
        raise ZoneNotFoundError(zone_id)

    latitude: float = float(zone["latitude"])
    longitude: float = float(zone["longitude"])

    # 2. Fetch from the configured provider
    fetch = get_provider(config)
    forecast_days: List[ForecastDay] = fetch(
        zone_id=zone_id,
        latitude=latitude,
        longitude=longitude,
        days=config.forecast_days,
        config=config,
    )

    # 3. Persist to the weather cache table (upsert, one row per day)
    weather_repo.put_forecast_days(
        zone_id=zone_id,
        days=[day.model_dump() for day in forecast_days],
    )

    logger.info(
        "Cached %d forecast days for zone=%s (provider=%s)",
        len(forecast_days),
        zone_id,
        config.weather_provider,
    )
    return forecast_days


def get_cached_forecast(
    zone_id: str,
    days: int | None = None,
    config: AppConfig | None = None,
) -> List[Dict[str, Any]]:
    """
    Return cached forecast rows for a zone. Raises WeatherUnavailableError
    if no rows are found (weather refresh has never run for this zone).
    """
    config = config or get_config()
    rows = weather_repo.get_forecast(zone_id, days=days or config.forecast_days)
    if not rows:
        raise WeatherUnavailableError(
            f"No cached forecast found for zone '{zone_id}'. "
            "Trigger a weather refresh first via POST /zones/{zone_id}/weather/refresh."
        )
    return rows


def refresh_all_zones(config: AppConfig | None = None) -> Dict[str, str]:
    """
    Refresh weather forecasts for all enabled zones. Used by the scheduled
    EventBridge Lambda (weather_refresh handler). Returns a summary dict of
    zone_id → "ok" | error message.
    """
    from src.repositories import zones as zones_repo  # local import avoids circular

    config = config or get_config()
    all_zones = zones_repo.list_zones()
    enabled_zones = [z for z in all_zones if z.get("enabled", True)]

    results: Dict[str, str] = {}
    for zone in enabled_zones:
        zid = zone["zone_id"]
        try:
            days = refresh_forecast(zid, config=config)
            results[zid] = f"ok ({len(days)} days)"
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Failed to refresh forecast for zone=%s", zid)
            results[zid] = f"error: {exc}"

    return results
