"""System router shim for SAM/Lambda."""
from __future__ import annotations

from typing import Any, Dict

from src.handlers import system as _system


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    method = (event.get("httpMethod") or "").upper()
    resource = event.get("resource") or event.get("path") or ""

    if method == "GET" and resource.endswith("/status"):
        return _system.get_status(event, context)
    if method == "GET" and resource.endswith("/activity"):
        return _system.list_activity(event, context)

    return {"statusCode": 405, "body": '{"error":"Method Not Allowed"}'}
