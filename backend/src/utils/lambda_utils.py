"""
Shared helpers for Lambda handlers: request parsing and a uniform
error-handling decorator so no handler ever leaks a stack trace, an AWS
error message, or a secret back to the client (spec section 18).
"""
from __future__ import annotations

import base64
import functools
import json
import logging
from typing import Any, Callable, Dict, Optional

from botocore.exceptions import BotoCoreError, ClientError
from pydantic import ValidationError as PydanticValidationError

from src.utils.errors import AppError, ExternalServiceError, ValidationError
from src.utils.responses import error_response

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def parse_body(event: Dict[str, Any]) -> Dict[str, Any]:
    """Parse the JSON body of an API Gateway proxy event. Returns {} for
    an empty body. Raises ValidationError for malformed JSON."""
    raw = event.get("body")
    if raw is None or raw == "":
        return {}
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValidationError("Request body must be valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise ValidationError("Request body must be a JSON object.")
    return parsed


def path_param(event: Dict[str, Any], name: str) -> Optional[str]:
    return (event.get("pathParameters") or {}).get(name)


def query_params(event: Dict[str, Any]) -> Dict[str, str]:
    return event.get("queryStringParameters") or {}


def pydantic_error_to_app_error(exc: PydanticValidationError) -> ValidationError:
    errors = exc.errors()
    if not errors:
        return ValidationError("Invalid request.")
    first = errors[0]
    field_name = ".".join(str(p) for p in first.get("loc", ())) or "input"
    return ValidationError(f"Invalid value for '{field_name}': {first.get('msg', 'invalid value')}.")


def handle_errors(func: Callable) -> Callable:
    """Wrap a Lambda handler so every exception becomes a well-formed,
    secret-free API error response instead of an unhandled crash."""

    @functools.wraps(func)
    def wrapper(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        try:
            return func(event, context)
        except AppError as exc:
            logger.warning("Handled application error: %s (%s)", exc.message, exc.code)
            return error_response(exc)
        except PydanticValidationError as exc:
            app_exc = pydantic_error_to_app_error(exc)
            logger.info("Request validation failed: %s", app_exc.message)
            return error_response(app_exc)
        except (ClientError, BotoCoreError):
            logger.exception("AWS service call failed")
            return error_response(ExternalServiceError("A backend service is temporarily unavailable. Please try again."))
        except Exception:
            logger.exception("Unhandled error in Lambda handler")
            return error_response(AppError("An unexpected error occurred.", code="INTERNAL_ERROR", status_code=500))

    return wrapper
