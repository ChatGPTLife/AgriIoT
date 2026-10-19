"""
Lambda handlers: email alert subscribers and manual alerts.

  POST   /subscribers                    — register {name, email, zone_ids?}; sends a welcome email
  GET    /subscribers                    — list subscribers (emails masked)
  DELETE /subscribers/{subscriber_id}    — unsubscribe
  POST   /zones/{zone_id}/alerts/trigger — evaluate the zone now and send the alert
                                           (SMS + email) regardless of cooldown
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from src.repositories import irrigation as irrigation_repo
from src.repositories import readings as readings_repo
from src.repositories import subscribers as subscribers_repo
from src.repositories import weather as weather_repo
from src.repositories import zones as zones_repo
from src.services import notifier
from src.services.email_service import mask_email, send_welcome_email
from src.services.irrigation_engine import IrrigationInputs, evaluate
from src.utils.config import get_config
from src.utils.errors import AppError, ValidationError, ZoneNotFoundError
from src.utils.ids import new_id, utc_now_iso
from src.utils.lambda_utils import handle_errors, parse_body, path_param
from src.utils.responses import success_response

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def _public(sub: Dict[str, Any]) -> Dict[str, Any]:
    return {**sub, "email": mask_email(sub["email"])}


@handle_errors
def create_subscriber(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    body = parse_body(event)
    name = str(body.get("name", "")).strip()
    email = str(body.get("email", "")).strip().lower()
    zone_ids: List[str] = body.get("zone_ids") or [subscribers_repo.ALL_ZONES]

    if not name or len(name) > 80:
        raise ValidationError("name is required (max 80 characters).")
    if not _EMAIL_RE.match(email):
        raise ValidationError("A valid email address is required.")
    if not isinstance(zone_ids, list) or not all(isinstance(z, str) for z in zone_ids):
        raise ValidationError("zone_ids must be a list of zone ids.")
    if subscribers_repo.find_by_email(email):
        raise AppError("This email address is already registered.", code="ALREADY_REGISTERED", status_code=409)

    zone_names: List[str] = []
    if subscribers_repo.ALL_ZONES not in zone_ids:
        for zid in zone_ids:
            zone = zones_repo.get_zone(zid)
            if zone is None:
                raise ZoneNotFoundError(zid)
            zone_names.append(zone.get("name", zid))

    subscriber = subscribers_repo.put_subscriber({
        "subscriber_id": new_id("sub"),
        "name": name,
        "email": email,
        "zone_ids": zone_ids,
        "active": True,
        "created_at": utc_now_iso(),
    })
    welcome = send_welcome_email(subscriber, zone_names)
    return success_response({"subscriber": _public(subscriber), "welcome_email": welcome}, status_code=201)


@handle_errors
def list_subscribers(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    subs = [_public(s) for s in subscribers_repo.list_subscribers()]
    return success_response({"subscribers": subs, "count": len(subs)})


@handle_errors
def delete_subscriber(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    sub_id = path_param(event, "subscriber_id") or ""
    if not subscribers_repo.delete_subscriber(sub_id):
        raise AppError(f"Subscriber '{sub_id}' not found.", code="NOT_FOUND", status_code=404)
    return success_response({"deleted": sub_id})


@handle_errors
def trigger_alert(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Manual alert: evaluate the zone from its latest reading + cached forecast,
    then send SMS and emails immediately (cooldown does not apply)."""
    config = get_config()
    zone_id = path_param(event, "zone_id") or ""
    zone = zones_repo.get_zone(zone_id)
    if zone is None:
        raise ZoneNotFoundError(zone_id)
    reading = readings_repo.get_latest_reading(zone_id)
    if reading is None:
        raise ValidationError("This zone has no sensor readings yet, so there is nothing to report.")

    try:
        forecast_summary = weather_repo.get_forecast_summary_for_decision(zone_id, window_days=config.forecast_window_days_for_rain)
    except Exception:  # pylint: disable=broad-except
        forecast_summary = {}

    decision = evaluate(IrrigationInputs(
        zone_id=zone_id,
        soil_moisture=float(reading["soil_moisture"]),
        moisture_threshold=float(zone["moisture_threshold"]),
        target_moisture=float(zone["target_moisture"]),
        temperature=reading.get("temperature"),
        humidity=reading.get("humidity"),
        forecast_rainfall_mm=forecast_summary.get("expected_rainfall_mm"),
        rain_probability=forecast_summary.get("rain_probability"),
        crop_type=zone.get("crop_type"),
        soil_type=zone.get("soil_type"),
        reading_id=reading.get("reading_id"),
    ), config=config)
    decision_dict = json.loads(decision.model_dump_json())
    irrigation_repo.put_decision(decision_dict)

    alert = notifier.raise_alert(zone, decision_dict, forecast_summary, reading=reading, trigger="manual", config=config)
    return success_response({"alert": alert, "decision": decision_dict}, status_code=201)
