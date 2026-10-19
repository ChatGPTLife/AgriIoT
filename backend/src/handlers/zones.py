"""
Lambda handler: Zones CRUD

Routes (API Gateway resource paths → HTTP methods):
  POST   /zones                 → create_zone
  GET    /zones                 → list_zones
  GET    /zones/{zone_id}       → get_zone
  PUT    /zones/{zone_id}       → update_zone
  DELETE /zones/{zone_id}       → delete_zone

Each exported function matches the signature expected by API Gateway Lambda
proxy integration: handler(event, context) → dict.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from src.models.zone import ZoneCreate, ZoneUpdate
from src.services import zone_service
from src.utils.lambda_utils import (
    handle_errors,
    parse_body,
    path_param,
    pydantic_error_to_app_error,
)
from src.utils.responses import success_response

from pydantic import ValidationError as PydanticValidationError

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


@handle_errors
def create_zone(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """POST /zones"""
    try:
        payload = ZoneCreate(**parse_body(event))
    except PydanticValidationError as exc:
        raise pydantic_error_to_app_error(exc) from exc

    zone = zone_service.create_zone(payload)
    logger.info("Created zone zone_id=%s", zone["zone_id"])
    return success_response({"zone": zone}, status_code=201)


@handle_errors
def list_zones(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """GET /zones"""
    zones = zone_service.list_zones()
    return success_response({"zones": zones, "count": len(zones)})


@handle_errors
def get_zone(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """GET /zones/{zone_id}"""
    zone_id = path_param(event, "zone_id") or ""
    zone = zone_service.get_zone_or_raise(zone_id)
    return success_response({"zone": zone})


@handle_errors
def update_zone(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """PUT /zones/{zone_id}"""
    zone_id = path_param(event, "zone_id") or ""
    try:
        payload = ZoneUpdate(**parse_body(event))
    except PydanticValidationError as exc:
        raise pydantic_error_to_app_error(exc) from exc

    zone = zone_service.update_zone(zone_id, payload)
    logger.info("Updated zone zone_id=%s", zone_id)
    return success_response({"zone": zone})


@handle_errors
def delete_zone(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """DELETE /zones/{zone_id}"""
    zone_id = path_param(event, "zone_id") or ""
    zone_service.delete_zone(zone_id)
    logger.info("Deleted zone zone_id=%s", zone_id)
    return success_response({"deleted": zone_id})
