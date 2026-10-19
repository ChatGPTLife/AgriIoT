"""Weather handler router shim for SAM/Lambda."""
from __future__ import annotations

from typing import Any, Dict

from src.handlers import weather as _weather


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    method = (event.get("httpMethod") or "").upper()
    resource = event.get("resource") or event.get("path") or ""

    # POST /zones/{zone_id}/weather/refresh
    if method == "POST" and "refresh" in resource:
        return _weather.refresh_weather(event, context)

    # GET /zones/{zone_id}/weather
    if method == "GET":
        return _weather.get_weather(event, context)

    return {"statusCode": 405, "body": '{"error":"Method Not Allowed"}'}
