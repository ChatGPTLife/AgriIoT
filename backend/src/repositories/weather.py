"""
Weather forecast cache repository.

Table: WeatherForecastCache (PK: zone_id, SK: forecast_date [YYYY-MM-DD])
Populated by the scheduled weather-refresh Lambda; read by the dashboard
and the irrigation engine. See docs/database.md.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from boto3.dynamodb.conditions import Key

from src.repositories.base import get_table
from src.utils.config import get_config
from src.utils.dynamo_serialization import from_dynamo, to_dynamo


def _table():
    return get_table(get_config().weather_cache_table)


def put_forecast_days(zone_id: str, days: List[Dict[str, Any]]) -> None:
    """Upsert one row per forecast day. Uses a batch writer since a
    refresh typically writes ~7 items for one zone."""
    with _table().batch_writer(overwrite_by_pkeys=["zone_id", "forecast_date"]) as batch:
        for day in days:
            batch.put_item(Item=to_dynamo(day))


def get_forecast(zone_id: str, days: Optional[int] = None) -> List[Dict[str, Any]]:
    """Cached forecast for a zone, ordered by forecast_date ascending."""
    kwargs: Dict[str, Any] = {"KeyConditionExpression": Key("zone_id").eq(zone_id), "ScanIndexForward": True}
    if days:
        kwargs["Limit"] = days
    resp = _table().query(**kwargs)
    return [from_dynamo(i) for i in resp.get("Items", [])]


def get_forecast_summary_for_decision(zone_id: str, window_days: int) -> Dict[str, float]:
    """Aggregate the next `window_days` cached forecast days into a single
    (expected_rainfall_mm, max_rain_probability) pair for the irrigation
    engine: total expected rainfall and the highest single-day probability
    within the window."""
    forecast = get_forecast(zone_id, days=window_days)
    total_rain = sum(day.get("precipitation_mm", 0.0) for day in forecast)
    max_probability = max((day.get("precipitation_probability", 0.0) for day in forecast), default=0.0)
    return {"expected_rainfall_mm": float(total_rain), "rain_probability": float(max_probability)}
