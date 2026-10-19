"""Alerts handler router shim for SAM/Lambda."""
from __future__ import annotations

from typing import Any, Dict

from src.handlers import alerts as _alerts


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    method = (event.get("httpMethod") or "").upper()
    resource = event.get("resource") or event.get("path") or ""

    if "{alert_id}" in resource:
        if method == "GET":
            return _alerts.get_alert(event, context)
        if method == "PATCH":
            return _alerts.acknowledge_alert(event, context)

    if method == "GET":
        return _alerts.list_alerts(event, context)

    return {"statusCode": 405, "body": '{"error":"Method Not Allowed"}'}
