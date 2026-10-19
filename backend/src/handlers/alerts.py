"""
Lambda handler: Alerts

Routes:
  GET   /alerts                    → list_alerts    (supports ?status=active&zone_id=...)
  GET   /alerts/{alert_id}         → get_alert
  PATCH /alerts/{alert_id}         → acknowledge_alert  (sets status=acknowledged)
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from src.repositories import alerts as alerts_repo
from src.utils.errors import AlertNotFoundError, ValidationError
from src.utils.ids import utc_now_iso
from src.utils.lambda_utils import handle_errors, parse_body, path_param, query_params
from src.utils.responses import success_response

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_ALLOWED_STATUSES = {"active", "acknowledged"}


@handle_errors
def list_alerts(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """GET /alerts"""
    qp = query_params(event)
    status = qp.get("status")
    zone_id = qp.get("zone_id")
    limit_str = qp.get("limit", "")
    limit = int(limit_str) if limit_str.isdigit() else None

    if status and status not in _ALLOWED_STATUSES:
        raise ValidationError(
            f"Invalid status '{status}'. Must be one of: {', '.join(sorted(_ALLOWED_STATUSES))}."
        )

    alert_list = alerts_repo.list_alerts(status=status, zone_id=zone_id, limit=limit)
    return success_response({"alerts": alert_list, "count": len(alert_list)})


@handle_errors
def get_alert(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """GET /alerts/{alert_id}"""
    alert_id = path_param(event, "alert_id") or ""
    alert = alerts_repo.get_alert(alert_id)
    if alert is None:
        raise AlertNotFoundError(alert_id)
    return success_response({"alert": alert})


@handle_errors
def acknowledge_alert(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """PATCH /alerts/{alert_id}  — acknowledge an active alert."""
    alert_id = path_param(event, "alert_id") or ""

    # Verify existence before updating
    existing = alerts_repo.get_alert(alert_id)
    if existing is None:
        raise AlertNotFoundError(alert_id)

    body = parse_body(event)
    new_status = body.get("status", "acknowledged")
    if new_status not in _ALLOWED_STATUSES:
        raise ValidationError(
            f"Invalid status '{new_status}'. Must be one of: {', '.join(sorted(_ALLOWED_STATUSES))}."
        )

    acknowledged_at = utc_now_iso() if new_status == "acknowledged" else None
    updated = alerts_repo.update_alert_status(
        alert_id, status=new_status, acknowledged_at=acknowledged_at
    )
    logger.info("Alert %s updated to status=%s", alert_id, new_status)
    return success_response({"alert": updated})
