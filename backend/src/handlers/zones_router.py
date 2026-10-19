"""
Zones router shim for SAM/Lambda.

SAM expects a single handler=module.function per Lambda function.
This module inspects the API Gateway event's httpMethod + resource and
dispatches to the correct handler function in src.handlers.zones.
"""
from __future__ import annotations

from typing import Any, Dict

from src.handlers import zones as _zones


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    method = (event.get("httpMethod") or "").upper()
    resource = event.get("resource") or event.get("path") or ""

    # /zones/{zone_id}
    if "{zone_id}" in resource:
        if method == "GET":
            return _zones.get_zone(event, context)
        if method == "PUT":
            return _zones.update_zone(event, context)
        if method == "DELETE":
            return _zones.delete_zone(event, context)

    # /zones
    if method == "POST":
        return _zones.create_zone(event, context)
    if method == "GET":
        return _zones.list_zones(event, context)

    return {"statusCode": 405, "body": '{"error":"Method Not Allowed"}'}
