"""
Alert dispatch: persists the alert, publishes SMS through Amazon SNS and
emails every subscriber registered for the zone.

Used by both the automatic path (sensor ingest → IRRIGATION_REQUIRED) and
the manual "trigger alert" endpoint.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from src.repositories import alerts as alerts_repo
from src.repositories import subscribers as subscribers_repo
from src.repositories import weather as weather_repo
from src.services import activity, email_service
from src.utils.config import AppConfig, get_config
from src.utils.ids import new_id, utc_now_iso

logger = logging.getLogger(__name__)


def cooldown_elapsed(zone_id: str, cooldown_minutes: int) -> bool:
    """Return True if enough time has passed since the last alert for this zone."""
    latest = alerts_repo.get_latest_alert_for_zone(zone_id)
    if latest is None:
        return True
    created_str: str = latest.get("created_at", "")
    try:
        created_at = datetime.fromisoformat(created_str)
    except (ValueError, TypeError):
        return True
    elapsed = datetime.now(timezone.utc) - created_at
    return elapsed >= timedelta(minutes=cooldown_minutes)


def _sns_error_code(exc: Exception) -> str:
    if isinstance(exc, ClientError):
        return exc.response.get("Error", {}).get("Code", "ClientError")
    return type(exc).__name__  # e.g. NoCredentialsError


def publish_sms(
    decision_dict: Dict[str, Any],
    zone: Dict[str, Any],
    config: AppConfig,
    trigger: str = "automatic",
) -> Optional[str]:
    """Publish an irrigation alert to the SNS topic and/or direct SMS numbers.
    Returns the SNS message ID, or None if SNS is not configured."""
    if not config.sns_topic_arn and not config.sns_sms_phone_numbers:
        logger.warning("SNS not configured — skipping alert publication.")
        return None

    sns = boto3.client("sns", region_name=config.aws_region)
    zone_name = zone.get("name", zone["zone_id"])
    urgency = decision_dict.get("urgency", "UNKNOWN")
    moisture = decision_dict.get("soil_moisture", 0)
    threshold = decision_dict.get("moisture_threshold", 0)
    reason = decision_dict.get("reason", "")
    recommendation = email_service.REC_LABEL.get(decision_dict.get("recommendation", ""), "")

    if trigger == "manual":
        subject = f"[MANUAL] {recommendation} — {zone_name}"
        header = f"MANUAL ALERT: {recommendation}"
    else:
        subject = f"[{urgency}] Irrigation required — {zone_name}"
        header = "IRRIGATION ALERT"
    message = (
        f"{header}\n"
        f"Zone: {zone_name}\n"
        f"Urgency: {urgency}\n"
        f"Soil moisture: {moisture:.1f}% (threshold: {threshold:.1f}%)\n"
        f"Reason: {reason}\n"
        f"Time: {utc_now_iso()} UTC"
    )

    message_id: Optional[str] = None

    # Publish to SNS topic
    if config.sns_topic_arn:
        try:
            resp = sns.publish(
                TopicArn=config.sns_topic_arn,
                Subject=subject[:100],
                Message=message,
                MessageAttributes={
                    "zone_id": {"DataType": "String", "StringValue": zone["zone_id"]},
                    "urgency": {"DataType": "String", "StringValue": urgency},
                },
            )
            message_id = resp.get("MessageId")
            logger.info("Published SNS alert for zone=%s urgency=%s MessageId=%s", zone["zone_id"], urgency, message_id)
            activity.record_sms(
                target=config.sns_topic_arn, target_type="topic", message=message,
                zone_id=zone["zone_id"], delivery=config.sns_mode, message_id=message_id, status="sent",
            )
        except (ClientError, BotoCoreError) as exc:
            logger.exception("Failed to publish SNS topic alert for zone=%s", zone["zone_id"])
            activity.record_sms(
                target=config.sns_topic_arn, target_type="topic", message=message,
                zone_id=zone["zone_id"], delivery=config.sns_mode, message_id=None, status="failed",
                error=_sns_error_code(exc),
            )

    # Also send direct SMS to explicitly configured phone numbers
    for phone in config.sns_sms_phone_numbers:
        try:
            sms_resp = sns.publish(
                PhoneNumber=phone,
                Message=message,
                MessageAttributes={
                    "AWS.SNS.SMS.SenderID": {"DataType": "String", "StringValue": "AgriIoT"},
                    "AWS.SNS.SMS.SMSType": {"DataType": "String", "StringValue": "Transactional"},
                },
            )
            logger.info("Sent direct SMS to %s for zone=%s", phone[:4] + "****", zone["zone_id"])
            activity.record_sms(
                target=phone, target_type="phone", message=message, zone_id=zone["zone_id"],
                delivery=config.sns_mode, message_id=sms_resp.get("MessageId"), status="sent",
            )
        except (ClientError, BotoCoreError) as exc:
            logger.exception("Failed to send SMS to %s for zone=%s", phone[:4] + "****", zone["zone_id"])
            activity.record_sms(
                target=phone, target_type="phone", message=message, zone_id=zone["zone_id"],
                delivery=config.sns_mode, message_id=None, status="failed",
                error=_sns_error_code(exc),
            )

    return message_id


def persist_alert(
    decision_dict: Dict[str, Any],
    zone: Dict[str, Any],
    forecast_summary: Dict[str, float],
    trigger: str = "automatic",
) -> Dict[str, Any]:
    alert = {
        "alert_id": new_id("alert"),
        "zone_id": zone["zone_id"],
        "zone_name": zone.get("name", zone["zone_id"]),
        "created_at": utc_now_iso(),
        "status": "active",
        "trigger": trigger,
        "recommendation": decision_dict.get("recommendation"),
        "urgency": decision_dict.get("urgency", "UNKNOWN"),
        "reason": decision_dict.get("reason", ""),
        "soil_moisture": decision_dict.get("soil_moisture", 0.0),
        "threshold": decision_dict.get("moisture_threshold", 0.0),
        "expected_rainfall_mm": forecast_summary.get("expected_rainfall_mm", 0.0),
        "rain_probability": forecast_summary.get("rain_probability", 0.0),
    }
    alerts_repo.create_alert(alert)
    return alert


def email_subscribers(
    zone: Dict[str, Any],
    decision_dict: Dict[str, Any],
    reading: Optional[Dict[str, Any]],
    forecast_summary: Dict[str, float],
    trigger: str,
    config: AppConfig,
) -> List[Dict[str, Any]]:
    try:
        recipients = subscribers_repo.subscribers_for_zone(zone["zone_id"])
    except (ClientError, BotoCoreError):
        # Email is best-effort: a subscriber lookup failure must not block the SMS alert.
        logger.exception("Could not load email subscribers for zone=%s", zone["zone_id"])
        return []
    if not recipients:
        return []
    try:
        forecast = weather_repo.get_forecast(zone["zone_id"], days=config.forecast_days)
    except Exception:  # pylint: disable=broad-except
        forecast = []
    subject, text, html_body = email_service.build_alert_email(
        zone, decision_dict, reading, forecast, forecast_summary, trigger
    )
    return [
        email_service.send_email(s["email"], subject, text, html_body, zone_id=zone["zone_id"], kind="alert", config=config)
        for s in recipients
    ]


def raise_alert(
    zone: Dict[str, Any],
    decision_dict: Dict[str, Any],
    forecast_summary: Dict[str, float],
    reading: Optional[Dict[str, Any]] = None,
    trigger: str = "automatic",
    config: AppConfig | None = None,
) -> Dict[str, Any]:
    """Send SMS + emails for an alert and persist it. Returns the alert with a
    `delivery` summary attached."""
    config = config or get_config()
    sms_id = publish_sms(decision_dict, zone, config, trigger=trigger)
    alert = persist_alert(decision_dict, zone, forecast_summary, trigger=trigger)
    emails = email_subscribers(zone, decision_dict, reading, forecast_summary, trigger, config)
    alert["delivery"] = {
        "sms_message_id": sms_id,
        "sms_mode": config.sns_mode,
        "emails": emails,
    }
    return alert
