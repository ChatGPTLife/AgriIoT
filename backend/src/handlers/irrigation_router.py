"""Irrigation handler router shim for SAM/Lambda."""
from __future__ import annotations

from typing import Any, Dict

from src.handlers import irrigation as _irrigation


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    method = (event.get("httpMethod") or "").upper()
    resource = event.get("resource") or event.get("path") or ""

    # GET /zones/{zone_id}/irrigation/latest
    if "{zone_id}" in resource and "latest" in resource and method == "GET":
        return _irrigation.get_latest_decision(event, context)

    # GET /irrigation/decisions
    if method == "GET":
        return _irrigation.list_decisions(event, context)

    return {"statusCode": 405, "body": '{"error":"Method Not Allowed"}'}
