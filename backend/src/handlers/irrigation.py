"""
Lambda handler: Irrigation decisions

Routes:
  GET /irrigation/decisions              → list_decisions   (cross-zone, with optional filters)
  GET /zones/{zone_id}/irrigation/latest → get_latest_decision (single zone)
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from src.repositories import irrigation as irrigation_repo
from src.utils.errors import ValidationError
from src.utils.lambda_utils import handle_errors, path_param, query_params
from src.utils.responses import success_response

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


@handle_errors
def list_decisions(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """GET /irrigation/decisions"""
    qp = query_params(event)
    zone_id = qp.get("zone_id")
    status = qp.get("status")          # maps to recommendation field
    date = qp.get("date")              # YYYY-MM-DD prefix filter
    limit_str = qp.get("limit", "")
    limit = int(limit_str) if limit_str.isdigit() else None

    # Basic date format validation
    if date and (len(date) != 10 or not date.replace("-", "").isdigit()):
        raise ValidationError("'date' query param must be in YYYY-MM-DD format.")

    decisions = irrigation_repo.list_decisions(
        zone_id=zone_id,
        status=status,
        date=date,
        limit=limit,
    )
    return success_response({"decisions": decisions, "count": len(decisions)})


@handle_errors
def get_latest_decision(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """GET /zones/{zone_id}/irrigation/latest"""
    zone_id = path_param(event, "zone_id") or ""

    decisions = irrigation_repo.list_decisions(zone_id=zone_id, limit=1)
    latest = decisions[0] if decisions else None
    return success_response({"zone_id": zone_id, "decision": latest})
