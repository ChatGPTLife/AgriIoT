"""
Lambda handlers: integration status and API activity log.

  GET /system/status    — which external services are configured (secrets masked)
  GET /system/activity  — recent weather API calls, sensor ingests, SMS deliveries
"""
from __future__ import annotations

from typing import Any, Dict

from src.repositories import activity as activity_repo
from src.repositories import subscribers as subscribers_repo
from src.services.activity import mask_phone, mask_secret
from src.services.email_service import mask_email
from src.utils.config import email_mode, get_config
from src.utils.errors import ValidationError
from src.utils.lambda_utils import handle_errors, query_params
from src.utils.responses import success_response

_WEATHER_ENDPOINTS = {
    "openweather": ("OpenWeatherMap One Call 3.0", "https://api.openweathermap.org/data/3.0/onecall"),
    "tomorrowio": ("Tomorrow.io Timelines v4", "https://api.tomorrow.io/v4/timelines"),
}


@handle_errors
def get_status(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """GET /system/status"""
    config = get_config()
    provider_name, endpoint = _WEATHER_ENDPOINTS.get(config.weather_provider, (config.weather_provider, None))
    api_key = config.openweather_api_key if config.weather_provider == "openweather" else config.tomorrowio_api_key

    return success_response(
        {
            "environment": config.environment,
            "region": config.aws_region,
            "weather": {
                "provider": config.weather_provider,
                "provider_name": provider_name,
                "endpoint": endpoint,
                "api_key_configured": bool(api_key),
                "api_key_masked": mask_secret(api_key),
                "forecast_days": config.forecast_days,
                "fallback": config.weather_fallback,
            },
            "sms": {
                "service": "Amazon SNS",
                "mode": config.sns_mode,
                "topic_configured": bool(config.sns_topic_arn),
                "topic_name": config.sns_topic_arn.split(":")[-1] if config.sns_topic_arn else None,
                "recipients": [mask_phone(p) for p in config.sns_sms_phone_numbers],
                "cooldown_minutes": config.alert_cooldown_minutes,
            },
            "email": {
                "service": "Gmail SMTP" if config.smtp_host == "smtp.gmail.com" else config.smtp_host,
                "mode": email_mode(config),
                "sender": mask_email(config.smtp_user) if config.smtp_user else None,
                "subscribers": len(subscribers_repo.list_subscribers()),
            },
            "storage": {"service": "Amazon DynamoDB"},
        }
    )


@handle_errors
def list_activity(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """GET /system/activity?stream=weather|sensor|sms&limit=50"""
    params = query_params(event)
    stream = params.get("stream", "weather")
    if stream not in activity_repo.STREAMS:
        raise ValidationError(f"stream must be one of: {', '.join(activity_repo.STREAMS)}.")
    try:
        limit = max(1, min(int(params.get("limit", 50)), 200))
    except ValueError as exc:
        raise ValidationError("limit must be an integer.") from exc

    events = activity_repo.list_events(stream, limit=limit)
    return success_response({"stream": stream, "events": events, "count": len(events)})
