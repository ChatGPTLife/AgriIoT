"""
Lambda handler: Sensor reading ingest  (POST /zones/{zone_id}/readings)

Full pipeline per call:
  1. Parse + validate JSON body via SensorReadingCreate pydantic model
  2. Assert the zone exists and is enabled
  3. Persist reading to DynamoDB (SensorReadings table)
  4. Fetch cached forecast summary (from WeatherForecastCache)
  5. Run the deterministic irrigation engine
  6. Persist the irrigation decision (IrrigationDecisions table)
  7. If recommendation == IRRIGATION_REQUIRED and cooldown has elapsed:
       a. Publish SNS topic notification
       b. Optionally publish direct SMS to configured phone numbers
       c. Persist the alert record (Alerts table)
  8. Return the irrigation decision in the API response

No ML. Every decision is fully traceable from inputs + config thresholds.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from pydantic import ValidationError as PydanticValidationError

from src.models.irrigation import Recommendation
from src.models.reading import SensorReadingCreate
from src.repositories import irrigation as irrigation_repo
from src.repositories import readings as readings_repo
from src.repositories import weather as weather_repo
from src.repositories import zones as zones_repo
from src.services import activity, notifier
from src.services.irrigation_engine import IrrigationInputs, evaluate
from src.utils.config import get_config
from src.utils.errors import ValidationError, ZoneDisabledError, ZoneNotFoundError
from src.utils.ids import new_id, utc_now_iso
from src.utils.lambda_utils import (
    handle_errors,
    parse_body,
    path_param,
    pydantic_error_to_app_error,
)
from src.utils.responses import success_response

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------

@handle_errors
def ingest_reading(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """POST /zones/{zone_id}/readings"""
    config = get_config()

    zone_id = path_param(event, "zone_id") or ""
    if not zone_id:
        raise ValidationError("zone_id path parameter is required.")

    # 1. Parse and validate body
    body = parse_body(event)
    # Allow zone_id in URL to override/set zone_id in body
    body["zone_id"] = zone_id
    try:
        payload = SensorReadingCreate(**body)
    except PydanticValidationError as exc:
        raise pydantic_error_to_app_error(exc) from exc

    # 2. Load zone (must exist and be enabled)
    zone = zones_repo.get_zone(zone_id)
    if zone is None:
        raise ZoneNotFoundError(zone_id)
    if not zone.get("enabled", True):
        raise ZoneDisabledError(zone_id)

    # 3. Persist the reading
    now = utc_now_iso()
    reading_id = new_id("rdg")
    reading = {
        "reading_id": reading_id,
        "zone_id": zone_id,
        "soil_moisture": payload.soil_moisture,
        "temperature": payload.temperature,
        "humidity": payload.humidity,
        "device_id": payload.device_id,
        "timestamp": now,
        "created_at": now,
    }
    readings_repo.put_reading(reading)
    logger.info(
        "Ingested reading reading_id=%s zone_id=%s moisture=%.1f%%",
        reading_id,
        zone_id,
        payload.soil_moisture,
    )

    # 4. Fetch cached forecast summary (non-fatal if unavailable)
    forecast_summary: Dict[str, float] = {}
    try:
        forecast_summary = weather_repo.get_forecast_summary_for_decision(
            zone_id, window_days=config.forecast_window_days_for_rain
        )
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "Could not load forecast for zone=%s — irrigation engine will use no-rain defaults.",
            zone_id,
        )

    # 5. Run the irrigation engine
    inputs = IrrigationInputs(
        zone_id=zone_id,
        soil_moisture=payload.soil_moisture,
        moisture_threshold=float(zone["moisture_threshold"]),
        target_moisture=float(zone["target_moisture"]),
        temperature=payload.temperature,
        humidity=payload.humidity,
        forecast_rainfall_mm=forecast_summary.get("expected_rainfall_mm"),
        rain_probability=forecast_summary.get("rain_probability"),
        crop_type=zone.get("crop_type"),
        soil_type=zone.get("soil_type"),
        reading_id=reading_id,
    )
    decision = evaluate(inputs, config=config)
    decision_dict = json.loads(decision.model_dump_json())

    # 6. Persist the irrigation decision
    irrigation_repo.put_decision(decision_dict)
    logger.info(
        "Irrigation decision zone_id=%s recommendation=%s urgency=%s",
        zone_id,
        decision.recommendation,
        decision.urgency,
    )

    # 7. Alert: only if irrigation is required AND cooldown has elapsed.
    #    SMS via SNS + email to every subscriber registered for this zone.
    alert_created: Optional[Dict[str, Any]] = None
    if (
        decision.recommendation == Recommendation.IRRIGATION_REQUIRED
        and notifier.cooldown_elapsed(zone_id, config.alert_cooldown_minutes)
    ):
        alert_created = notifier.raise_alert(zone, decision_dict, forecast_summary, reading=reading)
        logger.info(
            "Alert created alert_id=%s zone_id=%s",
            alert_created["alert_id"],
            zone_id,
        )
    elif decision.recommendation == Recommendation.IRRIGATION_REQUIRED:
        logger.info(
            "Irrigation required for zone=%s but alert cooldown has not elapsed — suppressing alert.",
            zone_id,
        )

    activity.record_sensor_ingest(zone_id, payload.device_id, decision.recommendation.value, payload.soil_moisture)

    # 8. Return decision (+ reading and alert ids for traceability)
    return success_response(
        {
            "decision": decision_dict,
            "reading_id": reading_id,
            "alert_id": alert_created["alert_id"] if alert_created else None,
        },
        status_code=201,
    )
