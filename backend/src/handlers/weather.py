"""
Lambda handler: Weather forecast

Routes:
  GET  /zones/{zone_id}/weather            → get_weather   (read DynamoDB cache)
  POST /zones/{zone_id}/weather/refresh    → refresh_weather (live API fetch)

The scheduled EventBridge weather-refresh Lambda also calls
weather_service.refresh_all_zones() directly (see weather_refresh below).
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from src.services import weather_service
from src.utils.lambda_utils import handle_errors, path_param, query_params
from src.utils.responses import success_response

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


@handle_errors
def get_weather(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """GET /zones/{zone_id}/weather"""
    zone_id = path_param(event, "zone_id") or ""
    qp = query_params(event)
    days = int(qp["days"]) if "days" in qp and qp["days"].isdigit() else None

    forecast = weather_service.get_cached_forecast(zone_id, days=days)
    return success_response({"zone_id": zone_id, "forecast": forecast, "days": len(forecast)})


@handle_errors
def refresh_weather(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """POST /zones/{zone_id}/weather/refresh — trigger a live weather API call."""
    zone_id = path_param(event, "zone_id") or ""
    forecast_days = weather_service.refresh_forecast(zone_id)
    return success_response(
        {
            "zone_id": zone_id,
            "refreshed": len(forecast_days),
            "forecast": [d.model_dump() for d in forecast_days],
        },
        status_code=200,
    )


@handle_errors
def weather_refresh_scheduled(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    EventBridge scheduled rule handler — refresh weather for ALL enabled zones.
    This function is invoked by the WeatherRefreshFunction Lambda every 6 hours.
    """
    logger.info("Scheduled weather refresh triggered. Event: %s", event)
    results = weather_service.refresh_all_zones()

    ok_count = sum(1 for v in results.values() if v.startswith("ok"))
    err_count = len(results) - ok_count
    logger.info(
        "Scheduled refresh complete: %d ok, %d errors. Results: %s",
        ok_count,
        err_count,
        results,
    )
    return success_response(
        {"refreshed": ok_count, "errors": err_count, "details": results}
    )
