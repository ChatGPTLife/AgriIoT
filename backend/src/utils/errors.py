"""
Domain-level application errors.

Every error carries a stable, machine-readable `code`, an HTTP
`status_code`, and a human-readable `message` that is always safe to
return to an API client — never a stack trace, never a secret.
See docs/api.md for the full error-code reference.
"""
from __future__ import annotations

from typing import Optional


class AppError(Exception):
    code = "INTERNAL_ERROR"
    status_code = 500

    def __init__(self, message: str, code: Optional[str] = None, status_code: Optional[int] = None):
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code


class ValidationError(AppError):
    code = "VALIDATION_ERROR"
    status_code = 400


class ZoneNotFoundError(AppError):
    code = "ZONE_NOT_FOUND"
    status_code = 404

    def __init__(self, zone_id: str):
        super().__init__(f"Zone '{zone_id}' does not exist.")
        self.zone_id = zone_id


class ZoneAlreadyExistsError(AppError):
    code = "ZONE_ALREADY_EXISTS"
    status_code = 409

    def __init__(self, zone_id: str):
        super().__init__(f"Zone '{zone_id}' already exists.")


class ZoneDisabledError(AppError):
    code = "ZONE_DISABLED"
    status_code = 409

    def __init__(self, zone_id: str):
        super().__init__(f"Zone '{zone_id}' is disabled and cannot accept sensor readings.")


class AlertNotFoundError(AppError):
    code = "ALERT_NOT_FOUND"
    status_code = 404

    def __init__(self, alert_id: str):
        super().__init__(f"Alert '{alert_id}' does not exist.")


class WeatherUnavailableError(AppError):
    """No cached forecast exists yet for a zone (e.g. before the first
    scheduled refresh has run)."""
    code = "WEATHER_UNAVAILABLE"
    status_code = 502


class ForecastIncompleteError(AppError):
    """Raised when a weather provider cannot supply the full required
    forecast window (e.g. fewer than FORECAST_DAYS days of daily data).
    The system must never silently substitute a shorter forecast for the
    required one, so this is surfaced as an explicit error rather than a
    partial success (see spec section 9)."""
    code = "FORECAST_INCOMPLETE"
    status_code = 502


class ExternalServiceError(AppError):
    code = "EXTERNAL_SERVICE_ERROR"
    status_code = 502


class ConfigurationError(AppError):
    code = "CONFIGURATION_ERROR"
    status_code = 500


class RateLimitedError(AppError):
    code = "RATE_LIMITED"
    status_code = 429


class UpstreamTimeoutError(AppError):
    code = "UPSTREAM_TIMEOUT"
    status_code = 504
