"""
Centralized application configuration.

Every configurable value is read from an environment variable so the same
code runs locally, in tests, and in AWS Lambda without modification. In
Lambda, these are set by infrastructure/template.yaml; locally they come
from a `.env` file (see .env.example) or your shell.

Nothing in this module ever hard-codes a secret, table name, ARN, or API
key — see section 19/26 of the project spec.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional, Tuple


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    return float(value) if value not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value not in (None, "") else default


@dataclass(frozen=True)
class AppConfig:
    # --- AWS / DynamoDB ---
    aws_region: str = field(default_factory=lambda: os.environ.get("AWS_REGION", "us-east-1"))
    dynamodb_endpoint_url: Optional[str] = field(default_factory=lambda: os.environ.get("DYNAMODB_ENDPOINT_URL") or None)

    zones_table: str = field(default_factory=lambda: os.environ.get("ZONES_TABLE", "AgriIot-Zones"))
    readings_table: str = field(default_factory=lambda: os.environ.get("READINGS_TABLE", "AgriIot-SensorReadings"))
    weather_cache_table: str = field(default_factory=lambda: os.environ.get("WEATHER_CACHE_TABLE", "AgriIot-WeatherForecastCache"))
    alerts_table: str = field(default_factory=lambda: os.environ.get("ALERTS_TABLE", "AgriIot-Alerts"))
    irrigation_decisions_table: str = field(default_factory=lambda: os.environ.get("IRRIGATION_DECISIONS_TABLE", "AgriIot-IrrigationDecisions"))
    activity_table: str = field(default_factory=lambda: os.environ.get("ACTIVITY_TABLE", "AgriIot-ApiActivity"))
    subscribers_table: str = field(default_factory=lambda: os.environ.get("SUBSCRIBERS_TABLE", "AgriIot-Subscribers"))

    # --- Email alerts (Gmail SMTP; needs a Google App Password) ---
    smtp_host: str = field(default_factory=lambda: os.environ.get("SMTP_HOST", "smtp.gmail.com"))
    smtp_port: int = field(default_factory=lambda: _env_int("SMTP_PORT", 465))
    smtp_user: Optional[str] = field(default_factory=lambda: os.environ.get("SMTP_USER") or None)
    smtp_app_password: Optional[str] = field(default_factory=lambda: (os.environ.get("SMTP_APP_PASSWORD") or "").replace(" ", "") or None)
    email_from_name: str = field(default_factory=lambda: os.environ.get("EMAIL_FROM_NAME", "AgriIoT Alerts"))

    # --- SNS ---
    sns_topic_arn: Optional[str] = field(default_factory=lambda: os.environ.get("SNS_TOPIC_ARN") or None)
    sns_sms_phone_numbers: Tuple[str, ...] = field(default_factory=lambda: tuple(
        p.strip() for p in os.environ.get("ALERT_SMS_PHONE_NUMBERS", "").split(",") if p.strip()
    ))
    # "aws" in deployed Lambda; local_server.py sets "mock" when SNS is simulated.
    sns_mode: str = field(default_factory=lambda: os.environ.get("SNS_MODE", "aws").lower())

    # --- Weather provider ---
    weather_provider: str = field(default_factory=lambda: os.environ.get("WEATHER_PROVIDER", "openweather").lower())
    openweather_api_key: Optional[str] = field(default_factory=lambda: os.environ.get("OPENWEATHER_API_KEY") or None)
    tomorrowio_api_key: Optional[str] = field(default_factory=lambda: os.environ.get("TOMORROWIO_API_KEY") or None)
    forecast_days: int = field(default_factory=lambda: _env_int("FORECAST_DAYS", 7))
    # "synthetic" = if the provider call fails, cache a generated forecast instead.
    weather_fallback: Optional[str] = field(default_factory=lambda: (os.environ.get("WEATHER_FALLBACK") or "").lower() or None)
    weather_http_timeout_seconds: float = field(default_factory=lambda: _env_float("WEATHER_HTTP_TIMEOUT_SECONDS", 8.0))

    # --- Irrigation decision engine thresholds ---
    rain_significant_mm: float = field(default_factory=lambda: _env_float("RAIN_SIGNIFICANT_MM", 5.0))
    rain_probability_threshold_pct: float = field(default_factory=lambda: _env_float("RAIN_PROBABILITY_THRESHOLD_PCT", 50.0))
    high_temperature_c: float = field(default_factory=lambda: _env_float("HIGH_TEMPERATURE_C", 32.0))
    forecast_window_days_for_rain: int = field(default_factory=lambda: _env_int("FORECAST_WINDOW_DAYS_FOR_RAIN", 2))

    # --- Alerts ---
    alert_cooldown_minutes: int = field(default_factory=lambda: _env_int("ALERT_COOLDOWN_MINUTES", 360))

    # --- API ---
    cors_allowed_origin: str = field(default_factory=lambda: os.environ.get("CORS_ALLOWED_ORIGIN", "*"))

    # --- General ---
    environment: str = field(default_factory=lambda: os.environ.get("APP_ENV", "local"))
    log_level: str = field(default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO"))


def email_mode(config: AppConfig) -> str:
    """"smtp" when sender credentials are configured, otherwise "mock"."""
    return "smtp" if config.smtp_user and config.smtp_app_password else "mock"


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    return AppConfig()


def reset_config_cache() -> None:
    """Test helper only: clears the cached config so a test can change
    environment variables and see them reflected in a fresh AppConfig."""
    get_config.cache_clear()
