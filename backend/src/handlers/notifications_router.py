"""Notifications router shim for SAM/Lambda (subscribers + manual alert trigger)."""
from __future__ import annotations

from typing import Any, Dict

from src.handlers import notifications as _n


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    method = (event.get("httpMethod") or "").upper()
    resource = event.get("resource") or event.get("path") or ""

    if resource.endswith("/alerts/trigger") and method == "POST":
        return _n.trigger_alert(event, context)
    if "{subscriber_id}" in resource and method == "DELETE":
        return _n.delete_subscriber(event, context)
    if resource.endswith("/subscribers"):
        if method == "POST":
            return _n.create_subscriber(event, context)
        if method == "GET":
            return _n.list_subscribers(event, context)

    return {"statusCode": 405, "body": '{"error":"Method Not Allowed"}'}
