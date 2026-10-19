"""
API Gateway (Lambda proxy integration) response helpers.

Every handler returns its response through `success_response` or
`error_response` so the API always uses the same envelope shape and the
same CORS headers, matching docs/api.md.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from src.utils.config import get_config
from src.utils.errors import AppError


def _headers() -> Dict[str, str]:
    origin = get_config().cors_allowed_origin
    return {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Headers": "Content-Type,Authorization",
        "Access-Control-Allow-Methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
    }


def _envelope(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": _headers(),
        "body": json.dumps(body, default=str),
    }


def success_response(payload: Optional[Dict[str, Any]] = None, status_code: int = 200) -> Dict[str, Any]:
    body: Dict[str, Any] = {"success": True}
    if payload:
        body.update(payload)
    return _envelope(status_code, body)


def error_response(exc: AppError) -> Dict[str, Any]:
    return _envelope(exc.status_code, {
        "success": False,
        "error": {"code": exc.code, "message": exc.message},
    })
