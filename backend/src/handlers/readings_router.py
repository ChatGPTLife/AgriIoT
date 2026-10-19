"""
Readings router shim for SAM/Lambda.

  POST /zones/{zone_id}/readings  — ingest (see sensor_ingest.py)
  GET  /zones/{zone_id}/readings  — reading history, ?hours=72 (max 168)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from src.handlers import sensor_ingest as _ingest
from src.repositories import readings as readings_repo
from src.repositories import zones as zones_repo
from src.utils.errors import ValidationError, ZoneNotFoundError
from src.utils.lambda_utils import handle_errors, path_param, query_params
from src.utils.responses import success_response


@handle_errors
def list_readings(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    zone_id = path_param(event, "zone_id") or ""
    if zones_repo.get_zone(zone_id) is None:
        raise ZoneNotFoundError(zone_id)
    try:
        hours = max(1, min(int(query_params(event).get("hours", 72)), 168))
    except ValueError as exc:
        raise ValidationError("hours must be an integer.") from exc

    start = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    readings = readings_repo.query_readings(zone_id, start=start)
    readings.reverse()  # oldest first, for charting
    return success_response({"zone_id": zone_id, "hours": hours, "readings": readings, "count": len(readings)})


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    method = (event.get("httpMethod") or "").upper()
    if method == "POST":
        return _ingest.ingest_reading(event, context)
    if method == "GET":
        return list_readings(event, context)
    return {"statusCode": 405, "body": '{"error":"Method Not Allowed"}'}
