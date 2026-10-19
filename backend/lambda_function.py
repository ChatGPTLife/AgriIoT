"""
AgriIoT — single-file AWS Lambda backend (paste into the Lambda console).

    Runtime: Python 3.12     Handler: lambda_function.lambda_handler
    Timeout: 30 s            Memory: 256 MB
    Dependencies: none beyond boto3 (built into the Lambda runtime)

API Gateway: one REST API (or HTTP API) with a `/{proxy+}` resource, method ANY,
Lambda proxy integration → this function. Optionally an EventBridge schedule
(e.g. rate(6 hours)) → this function to refresh every zone's forecast.

What it does
  • Receives soil sensor readings (POST /zones/{id}/readings or POST /api/sensor-data)
  • Fetches a genuine 7-day forecast from OpenWeatherMap One Call 3.0
  • Decides whether irrigation is needed (soil moisture + forecast rainfall)
  • Stores readings, forecasts, decisions and alerts in DynamoDB
  • Emails alerts through Amazon SES (no SNS / SMS)

Forecast honesty: forecasts are never invented. If the weather API fails, the
decision is marked forecast_available = false and its reason says so; rainfall
is NOT silently assumed to be zero.

Environment variables (see .env.example):
  OPENWEATHER_API_KEY        required for forecasts (One Call 3.0 subscription)
  SES_SENDER_EMAIL           verified SES identity used as From
  ALERT_EMAIL_TO             optional, comma-separated fixed recipients
  ZONES_TABLE, READINGS_TABLE, WEATHER_CACHE_TABLE, ALERTS_TABLE,
  IRRIGATION_DECISIONS_TABLE, ACTIVITY_TABLE, SUBSCRIBERS_TABLE
  Optional tuning: FORECAST_DAYS=7, FORECAST_MAX_AGE_HOURS=12, RAIN_SIGNIFICANT_MM=5,
  RAIN_PROBABILITY_THRESHOLD_PCT=50, FORECAST_WINDOW_DAYS_FOR_RAIN=2, HIGH_TEMPERATURE_C=32,
  DEFAULT_MOISTURE_THRESHOLD=25, ALERT_COOLDOWN_MINUTES=360, CORS_ALLOWED_ORIGIN=*,
  WEATHER_HTTP_TIMEOUT_SECONDS=8
  The thresholds are EXAMPLE values for a demonstration, not agronomic advice.

IAM (least privilege): dynamodb:GetItem/PutItem/UpdateItem/DeleteItem/Query/Scan/
BatchWriteItem on the 7 tables and their /index/*; ses:SendEmail + ses:SendRawEmail
on the sender identity; ses:VerifyEmailIdentity (sandbox subscriber verification);
plus AWSLambdaBasicExecutionRole for CloudWatch Logs.
"""
from __future__ import annotations

import base64
import html
import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Tuple

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


# ─── Configuration ──────────────────────────────────────────────────────────

def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_num(name: str, default: float) -> float:
    value = os.environ.get(name, "").strip()
    return float(value) if value else default


TABLES = {
    "zones": _env("ZONES_TABLE", "AgriIot-Zones"),
    "readings": _env("READINGS_TABLE", "AgriIot-SensorReadings"),
    "weather": _env("WEATHER_CACHE_TABLE", "AgriIot-WeatherForecastCache"),
    "alerts": _env("ALERTS_TABLE", "AgriIot-Alerts"),
    "decisions": _env("IRRIGATION_DECISIONS_TABLE", "AgriIot-IrrigationDecisions"),
    "activity": _env("ACTIVITY_TABLE", "AgriIot-ApiActivity"),
    "subscribers": _env("SUBSCRIBERS_TABLE", "AgriIot-Subscribers"),
}
OPENWEATHER_URL = "https://api.openweathermap.org/data/3.0/onecall"
FORECAST_DAYS = int(_env_num("FORECAST_DAYS", 7))
FORECAST_MAX_AGE_HOURS = _env_num("FORECAST_MAX_AGE_HOURS", 12)
RAIN_SIGNIFICANT_MM = _env_num("RAIN_SIGNIFICANT_MM", 5.0)
RAIN_PROBABILITY_PCT = _env_num("RAIN_PROBABILITY_THRESHOLD_PCT", 50.0)
RAIN_WINDOW_DAYS = int(_env_num("FORECAST_WINDOW_DAYS_FOR_RAIN", 2))
HIGH_TEMPERATURE_C = _env_num("HIGH_TEMPERATURE_C", 32.0)
DEFAULT_MOISTURE_THRESHOLD = _env_num("DEFAULT_MOISTURE_THRESHOLD", 25.0)
ALERT_COOLDOWN_MINUTES = _env_num("ALERT_COOLDOWN_MINUTES", 360)
HTTP_TIMEOUT = _env_num("WEATHER_HTTP_TIMEOUT_SECONDS", 8)
CORS_ORIGIN = _env("CORS_ALLOWED_ORIGIN", "*")
HIGH_DEFICIT_PCT, MEDIUM_DEFICIT_PCT = 15.0, 7.0
ACTIVITY_TTL_DAYS = 7

_dynamodb = boto3.resource("dynamodb")
_ses = boto3.client("ses")


def table(name: str):
    return _dynamodb.Table(TABLES[name])


# ─── Small helpers ──────────────────────────────────────────────────────────

class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def slugify(text: str) -> str:
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", text.strip().lower())).strip("-") or "zone"


def to_dynamo(value: Any) -> Any:
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: to_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_dynamo(v) for v in value]
    return value


def from_dynamo(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: from_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [from_dynamo(v) for v in value]
    return value


def mask(value: Optional[str], keep: int = 4) -> Optional[str]:
    return "•" * 6 + value[-keep:] if value else None


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:2]}{'•' * max(len(local) - 2, 3)}@{domain}"


def response(status: int, body: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": CORS_ORIGIN,
            "Access-Control-Allow-Headers": "Content-Type,Authorization,x-api-key",
            "Access-Control-Allow-Methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
        },
        "body": json.dumps(body, default=str),
    }


def ok(data: Dict[str, Any], status: int = 200) -> Dict[str, Any]:
    return response(status, {"success": True, **data})


def number(body: Dict[str, Any], field: str, lo: float, hi: float, required: bool = True) -> Optional[float]:
    value = body.get(field)
    if value is None:
        if required:
            raise ApiError(400, "VALIDATION_ERROR", f"'{field}' is required.")
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(400, "VALIDATION_ERROR", f"'{field}' must be a number.")
    if not lo <= value <= hi:
        raise ApiError(400, "VALIDATION_ERROR", f"'{field}' must be between {lo:g} and {hi:g}.")
    return float(value)


def text(body: Dict[str, Any], field: str, max_len: int = 100, required: bool = True) -> Optional[str]:
    value = body.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ApiError(400, "VALIDATION_ERROR", f"'{field}' is required.")
        return None
    if not isinstance(value, str) or len(value) > max_len:
        raise ApiError(400, "VALIDATION_ERROR", f"'{field}' must be text (max {max_len} characters).")
    return value.strip()


def record_activity(stream: str, event: Dict[str, Any]) -> Dict[str, Any]:
    """Best-effort activity log for the dashboard's Integrations page."""
    item = {"event_id": new_id("evt"), "stream": stream, "created_at": now_iso(),
            "expires_at": int(time.time()) + ACTIVITY_TTL_DAYS * 86400, **event}
    try:
        table("activity").put_item(Item=to_dynamo(item))
    except (ClientError, BotoCoreError):
        logger.warning("Could not record %s activity", stream, exc_info=True)
    return item


# ─── Zones ──────────────────────────────────────────────────────────────────

def get_zone_or_404(zone_id: str) -> Dict[str, Any]:
    item = table("zones").get_item(Key={"zone_id": zone_id}).get("Item")
    if not item:
        raise ApiError(404, "ZONE_NOT_FOUND", f"Zone '{zone_id}' does not exist.")
    return from_dynamo(item)


def list_zones() -> List[Dict[str, Any]]:
    tbl, items, kwargs = table("zones"), [], {}
    while True:
        resp = tbl.scan(**kwargs)
        items += resp.get("Items", [])
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return sorted((from_dynamo(i) for i in items), key=lambda z: z.get("name", ""))


def validate_zone(body: Dict[str, Any], partial: bool = False) -> Dict[str, Any]:
    req = not partial
    fields = {
        "name": text(body, "name", 100, req),
        "latitude": number(body, "latitude", -90, 90, req),
        "longitude": number(body, "longitude", -180, 180, req),
        "crop_type": text(body, "crop_type", 100, req),
        "soil_type": text(body, "soil_type", 100, req),
        "moisture_threshold": number(body, "moisture_threshold", 0, 100, req),
        "target_moisture": number(body, "target_moisture", 0, 100, req),
    }
    if "enabled" in body:
        if not isinstance(body["enabled"], bool):
            raise ApiError(400, "VALIDATION_ERROR", "'enabled' must be true or false.")
        fields["enabled"] = body["enabled"]
    return {k: v for k, v in fields.items() if v is not None}


def create_zone_record(fields: Dict[str, Any], zone_id: Optional[str] = None) -> Dict[str, Any]:
    zone_id = zone_id or slugify(fields["name"])
    stamp = now_iso()
    zone = {"zone_id": zone_id, "enabled": True, **fields, "created_at": stamp, "updated_at": stamp}
    try:
        table("zones").put_item(Item=to_dynamo(zone), ConditionExpression="attribute_not_exists(zone_id)")
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise ApiError(409, "ZONE_ALREADY_EXISTS", f"Zone '{zone_id}' already exists.") from exc
        raise
    return zone


def api_create_zone(ev: "Req") -> Dict[str, Any]:
    zone_id = text(ev.body, "zone_id", 64, required=False)
    return ok({"zone": create_zone_record(validate_zone(ev.body), slugify(zone_id) if zone_id else None)}, 201)


def api_update_zone(ev: "Req") -> Dict[str, Any]:
    zone = get_zone_or_404(ev.params["zone_id"])
    updates = validate_zone(ev.body, partial=True)
    if not updates:
        raise ApiError(400, "VALIDATION_ERROR", "No updatable fields supplied.")
    zone.update(updates, updated_at=now_iso())
    table("zones").put_item(Item=to_dynamo(zone))
    return ok({"zone": zone})


def api_delete_zone(ev: "Req") -> Dict[str, Any]:
    get_zone_or_404(ev.params["zone_id"])
    table("zones").delete_item(Key={"zone_id": ev.params["zone_id"]})
    return ok({"deleted": ev.params["zone_id"]})


# ─── Weather (OpenWeatherMap One Call 3.0 — real data only) ─────────────────

def fetch_openweather(zone: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Fetch a 7-day daily forecast. Raises ApiError on any failure — never invents data."""
    key = _env("OPENWEATHER_API_KEY")
    if not key:
        raise ApiError(500, "CONFIGURATION_ERROR", "OPENWEATHER_API_KEY is not configured.")
    lat, lon = float(zone["latitude"]), float(zone["longitude"])
    query = urllib.parse.urlencode({"lat": lat, "lon": lon, "units": "metric", "appid": key,
                                    "exclude": "current,minutely,hourly,alerts"})
    log = {"kind": "weather", "direction": "outbound", "provider": "OpenWeatherMap One Call 3.0",
           "method": "GET", "zone_id": zone["zone_id"], "api_key_masked": mask(key),
           "endpoint": f"{OPENWEATHER_URL}?lat={lat:.4f}&lon={lon:.4f}&units=metric&appid={mask(key)}"}
    started = time.perf_counter()

    def fail(status: Optional[int], api_status: int, code: str, message: str) -> ApiError:
        record_activity("weather", {**log, "status": "error", "http_status": status,
                                    "latency_ms": round((time.perf_counter() - started) * 1000), "summary": message})
        return ApiError(api_status, code, message)

    try:
        with urllib.request.urlopen(f"{OPENWEATHER_URL}?{query}", timeout=HTTP_TIMEOUT) as resp:
            payload = json.loads(resp.read())
            http_status = resp.status
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise fail(401, 502, "WEATHER_AUTH_FAILED",
                       "OpenWeatherMap rejected the key (invalid, or One Call 3.0 subscription not active).")
        if exc.code == 429:
            raise fail(429, 503, "WEATHER_RATE_LIMITED", "OpenWeatherMap rate limit reached. Try again later.")
        raise fail(exc.code, 502, "WEATHER_UNAVAILABLE", f"OpenWeatherMap returned HTTP {exc.code}.")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise fail(None, 504, "WEATHER_TIMEOUT", f"Could not reach OpenWeatherMap ({type(exc).__name__}).")
    except json.JSONDecodeError:
        raise fail(200, 502, "WEATHER_BAD_RESPONSE", "OpenWeatherMap returned an unreadable response.")

    fetched_at = now_iso()
    days = []
    for d in payload.get("daily", [])[:FORECAST_DAYS]:
        weather = (d.get("weather") or [{}])[0]
        days.append({
            "zone_id": zone["zone_id"],
            "forecast_date": datetime.fromtimestamp(d["dt"], tz=timezone.utc).strftime("%Y-%m-%d"),
            "fetched_at": fetched_at,
            "temperature_min": float(d.get("temp", {}).get("min", 0.0)),
            "temperature_max": float(d.get("temp", {}).get("max", 0.0)),
            "humidity": float(d.get("humidity", 0.0)),
            "precipitation_mm": float(d.get("rain", 0.0) or 0.0),
            "precipitation_probability": round(float(d.get("pop", 0.0) or 0.0) * 100),
            "condition": (weather.get("main") or "unknown").lower().replace(" ", "_"),
            "provider": "openweather",
        })
    if len(days) < FORECAST_DAYS:
        raise fail(http_status, 502, "FORECAST_INCOMPLETE",
                   f"OpenWeatherMap returned {len(days)} day(s); {FORECAST_DAYS} are required.")

    record_activity("weather", {**log, "status": "success", "http_status": http_status,
                                "latency_ms": round((time.perf_counter() - started) * 1000),
                                "summary": f"HTTP {http_status} · {len(days)} days"})
    return days


def refresh_forecast(zone: Dict[str, Any]) -> List[Dict[str, Any]]:
    days = fetch_openweather(zone)
    with table("weather").batch_writer(overwrite_by_pkeys=["zone_id", "forecast_date"]) as batch:
        for day in days:
            batch.put_item(Item=to_dynamo(day))
    return days


def cached_forecast(zone_id: str) -> List[Dict[str, Any]]:
    today = date.today().isoformat()
    resp = table("weather").query(KeyConditionExpression=Key("zone_id").eq(zone_id) & Key("forecast_date").gte(today))
    return [from_dynamo(i) for i in resp.get("Items", [])][:FORECAST_DAYS]


def forecast_for_decision(zone: Dict[str, Any]) -> Tuple[Optional[Dict[str, float]], List[Dict[str, Any]], Optional[str]]:
    """Return (rain summary | None, forecast rows, error message). Refreshes a stale cache first."""
    rows = cached_forecast(zone["zone_id"])
    fresh = rows and datetime.fromisoformat(rows[0]["fetched_at"]) > datetime.now(timezone.utc) - timedelta(hours=FORECAST_MAX_AGE_HOURS)
    error = None
    if not fresh:
        try:
            rows = refresh_forecast(zone)
        except ApiError as exc:
            error = exc.message
            if not rows:
                return None, [], error
    window = rows[:RAIN_WINDOW_DAYS]
    summary = {
        "expected_rainfall_mm": round(sum(d["precipitation_mm"] for d in window), 1),
        "rain_probability": max((d["precipitation_probability"] for d in window), default=0),
    }
    return summary, rows, error


def api_get_weather(ev: "Req") -> Dict[str, Any]:
    get_zone_or_404(ev.params["zone_id"])
    rows = cached_forecast(ev.params["zone_id"])
    return ok({"zone_id": ev.params["zone_id"], "forecast": rows, "days": len(rows)})


def api_refresh_weather(ev: "Req") -> Dict[str, Any]:
    zone = get_zone_or_404(ev.params["zone_id"])
    days = refresh_forecast(zone)
    return ok({"zone_id": zone["zone_id"], "refreshed": len(days), "forecast": days})


# ─── Irrigation decision engine ─────────────────────────────────────────────

def evaluate(zone: Dict[str, Any], moisture: float, temperature: Optional[float], humidity: Optional[float],
             rain: Optional[Dict[str, float]], forecast_error: Optional[str], reading_id: str) -> Dict[str, Any]:
    threshold = float(zone["moisture_threshold"])
    decision = {
        "zone_id": zone["zone_id"], "evaluated_at": now_iso(), "record_type": "DECISION",
        "soil_moisture": moisture, "moisture_threshold": threshold,
        "target_moisture": float(zone["target_moisture"]), "temperature": temperature, "humidity": humidity,
        "forecast_available": rain is not None,
        "forecast_rainfall_mm": rain["expected_rainfall_mm"] if rain else None,
        "rain_probability": rain["rain_probability"] if rain else None,
        "reading_id": reading_id,
    }
    if moisture >= threshold:
        return {**decision, "recommendation": "NO_IRRIGATION_NEEDED", "urgency": "NONE",
                "reason": f"Soil moisture ({moisture:.1f}%) is at or above the threshold ({threshold:.1f}%)."}

    deficit = threshold - moisture
    urgency = "HIGH" if deficit >= HIGH_DEFICIT_PCT else "MEDIUM" if deficit >= MEDIUM_DEFICIT_PCT else "LOW"

    if rain is None:
        # Never treat a failed forecast as "no rain": say so explicitly.
        return {**decision, "recommendation": "IRRIGATION_REQUIRED", "urgency": urgency,
                "reason": (f"Soil moisture ({moisture:.1f}%) is below the threshold ({threshold:.1f}%). "
                           f"The weather forecast is UNAVAILABLE ({forecast_error}), so expected rainfall could "
                           f"not be checked — verify the forecast before irrigating.")}

    if rain["expected_rainfall_mm"] >= RAIN_SIGNIFICANT_MM and rain["rain_probability"] >= RAIN_PROBABILITY_PCT:
        return {**decision, "recommendation": "WAIT_FOR_RAIN", "urgency": "LOW" if deficit < MEDIUM_DEFICIT_PCT else "MEDIUM",
                "reason": (f"Soil moisture ({moisture:.1f}%) is below the threshold ({threshold:.1f}%), but "
                           f"{rain['expected_rainfall_mm']:.1f} mm of rain is expected ({rain['rain_probability']:.0f}% chance) "
                           f"within {RAIN_WINDOW_DAYS} day(s), so irrigation is being held off.")}

    if temperature is not None and temperature >= HIGH_TEMPERATURE_C:
        urgency = {"LOW": "MEDIUM", "MEDIUM": "HIGH"}.get(urgency, urgency)
    reason = (f"Soil moisture ({moisture:.1f}%) is below the threshold ({threshold:.1f}%) and only "
              f"{rain['expected_rainfall_mm']:.1f} mm of rain is forecast in the next {RAIN_WINDOW_DAYS} day(s).")
    if temperature is not None and temperature >= HIGH_TEMPERATURE_C:
        reason += f" High temperature ({temperature:.1f}°C) increases urgency."
    return {**decision, "recommendation": "IRRIGATION_REQUIRED", "urgency": urgency, "reason": reason}


# ─── Email alerts (Amazon SES) ──────────────────────────────────────────────

REC_LABEL = {"IRRIGATION_REQUIRED": "Irrigation required", "WAIT_FOR_RAIN": "Hold irrigation — rain expected",
             "NO_IRRIGATION_NEEDED": "No irrigation needed"}


def list_subscribers() -> List[Dict[str, Any]]:
    return sorted((from_dynamo(i) for i in table("subscribers").scan().get("Items", [])),
                  key=lambda s: s.get("created_at", ""))


def alert_recipients(zone_id: str) -> List[str]:
    fixed = [e.strip().lower() for e in _env("ALERT_EMAIL_TO").split(",") if e.strip()]
    try:
        subs = [s["email"] for s in list_subscribers()
                if s.get("active", True) and ("*" in s.get("zone_ids", []) or zone_id in s.get("zone_ids", []))]
    except (ClientError, BotoCoreError):
        logger.exception("Could not load subscribers")
        subs = []
    return list(dict.fromkeys(fixed + subs))


def send_email(to: str, subject: str, body_text: str, body_html: str, zone_id: Optional[str], kind: str) -> Dict[str, Any]:
    sender = _env("SES_SENDER_EMAIL")
    status, error, message_id = "sent", None, None
    if not sender:
        status, error = "failed", "SES_SENDER_EMAIL not configured"
    else:
        try:
            resp = _ses.send_email(
                Source=f"AgriIoT Alerts <{sender}>",
                Destination={"ToAddresses": [to]},
                Message={"Subject": {"Data": subject, "Charset": "UTF-8"},
                         "Body": {"Text": {"Data": body_text, "Charset": "UTF-8"},
                                  "Html": {"Data": body_html, "Charset": "UTF-8"}}},
            )
            message_id = resp.get("MessageId")
        except ClientError as exc:
            status, error = "failed", exc.response["Error"].get("Code", "ClientError")
            if error == "MessageRejected":
                error = "MessageRejected (SES sandbox: recipient email not verified yet)"
        except BotoCoreError as exc:
            status, error = "failed", type(exc).__name__
    evt = record_activity("email", {"kind": kind, "target": mask_email(to), "subject": subject, "message": body_text,
                                    "zone_id": zone_id, "delivery": "ses", "status": status, "error": error,
                                    "message_id": message_id})
    if status == "failed":
        logger.warning("SES email to %s failed: %s", mask_email(to), error)
    return {"to": mask_email(to), "status": status, "error": error, "event_id": evt["event_id"]}


def build_alert_email(zone: Dict[str, Any], d: Dict[str, Any], reading: Dict[str, Any],
                      forecast: List[Dict[str, Any]], trigger: str) -> Tuple[str, str, str]:
    label = REC_LABEL.get(d["recommendation"], d["recommendation"])
    prefix = "Manual alert" if trigger == "manual" else "Alert"
    subject = f"[AgriIoT] {prefix}: {label} — {zone.get('name', zone['zone_id'])}"
    rain_line = (f"Next {RAIN_WINDOW_DAYS} days: {d['forecast_rainfall_mm']:.1f} mm forecast, up to {d['rain_probability']:.0f}% chance"
                 if d["forecast_available"] else "Weather forecast UNAVAILABLE — rainfall could not be checked")
    lines = [f"{prefix.upper()}: {label} (urgency {d['urgency']})",
             f"Farm / zone: {zone.get('name')} ({zone['zone_id']})",
             f"Soil moisture: {d['soil_moisture']:.1f}% (threshold {d['moisture_threshold']:.0f}%)",
             f"Temperature: {reading.get('temperature')} °C   Humidity: {reading.get('humidity')}%",
             rain_line, ""]
    lines += [f"  {f['forecast_date']}: {f['condition']}, {f['temperature_max']:.0f}°/{f['temperature_min']:.0f}°, "
              f"{f['precipitation_mm']:.1f} mm ({f['precipitation_probability']:.0f}%)" for f in forecast[:5]]
    lines += ["", f"Why: {d['reason']}", f"Sent {now_iso()[:16].replace('T', ' ')} UTC by AgriIoT."]
    body_text = "\n".join(lines)
    rows = "".join(f"<tr><td>{f['forecast_date']}</td><td>{html.escape(f['condition'])}</td>"
                   f"<td>{f['temperature_max']:.0f}° / {f['temperature_min']:.0f}°</td>"
                   f"<td>{f['precipitation_mm']:.1f} mm</td><td>{f['precipitation_probability']:.0f}%</td></tr>"
                   for f in forecast[:5])
    body_html = (f"<div style='font-family:Arial,sans-serif;max-width:600px'>"
                 f"<h2 style='color:#eb6e4b'>🌱 AgriIoT · {html.escape(prefix)}</h2>"
                 f"<p><b>{html.escape(label)}</b> (urgency {d['urgency']}) — <b>{html.escape(zone.get('name', ''))}</b> "
                 f"({html.escape(zone['zone_id'])})</p>"
                 f"<p>Soil moisture: <b>{d['soil_moisture']:.1f}%</b> (threshold {d['moisture_threshold']:.0f}%)<br>"
                 f"Temperature: {reading.get('temperature')} °C · Humidity: {reading.get('humidity')}%<br>"
                 f"{html.escape(rain_line)}</p>"
                 f"<table border='1' cellpadding='6' style='border-collapse:collapse;font-size:13px'>"
                 f"<tr><th>Date</th><th>Conditions</th><th>High / Low</th><th>Rain</th><th>Chance</th></tr>{rows}</table>"
                 f"<p><b>Why:</b> {html.escape(d['reason'])}</p></div>")
    return subject, body_text, body_html


def cooldown_elapsed(zone_id: str) -> bool:
    resp = table("alerts").query(IndexName="ZoneIndex", KeyConditionExpression=Key("zone_id").eq(zone_id),
                                 ScanIndexForward=False, Limit=1)
    items = resp.get("Items", [])
    if not items:
        return True
    last = datetime.fromisoformat(items[0]["created_at"])
    return datetime.now(timezone.utc) - last >= timedelta(minutes=ALERT_COOLDOWN_MINUTES)


def raise_alert(zone: Dict[str, Any], decision: Dict[str, Any], reading: Dict[str, Any],
                forecast: List[Dict[str, Any]], trigger: str) -> Dict[str, Any]:
    alert = {
        "alert_id": new_id("alert"), "zone_id": zone["zone_id"], "zone_name": zone.get("name", zone["zone_id"]),
        "created_at": now_iso(), "status": "active", "trigger": trigger,
        "recommendation": decision["recommendation"], "urgency": decision["urgency"], "reason": decision["reason"],
        "soil_moisture": decision["soil_moisture"], "threshold": decision["moisture_threshold"],
        "forecast_available": decision["forecast_available"],
        "expected_rainfall_mm": decision["forecast_rainfall_mm"] or 0.0,
        "rain_probability": decision["rain_probability"] or 0.0,
    }
    table("alerts").put_item(Item=to_dynamo(alert))
    subject, body_text, body_html = build_alert_email(zone, decision, reading, forecast, trigger)
    emails = [send_email(to, subject, body_text, body_html, zone["zone_id"], "alert") for to in alert_recipients(zone["zone_id"])]
    return {**alert, "delivery": {"sms_message_id": None, "sms_mode": "disabled", "emails": emails}}


# ─── Sensor readings ────────────────────────────────────────────────────────

def ingest(zone: Dict[str, Any], body: Dict[str, Any]) -> Dict[str, Any]:
    if not zone.get("enabled", True):
        raise ApiError(409, "ZONE_DISABLED", f"Zone '{zone['zone_id']}' is disabled.")
    moisture = number(body, "soil_moisture", 0, 100)
    temperature = number(body, "temperature", -40, 70)
    humidity = number(body, "humidity", 0, 100)
    device_id = text(body, "device_id", 100, required=False)

    stamp = now_iso()
    reading = {"reading_id": new_id("rdg"), "zone_id": zone["zone_id"], "device_id": device_id,
               "soil_moisture": moisture, "temperature": temperature, "humidity": humidity,
               "timestamp": stamp, "created_at": stamp}
    table("readings").put_item(Item=to_dynamo(reading))

    rain, forecast, forecast_error = forecast_for_decision(zone)
    decision = evaluate(zone, moisture, temperature, humidity, rain, forecast_error, reading["reading_id"])
    table("decisions").put_item(Item=to_dynamo(decision))

    alert = None
    if decision["recommendation"] == "IRRIGATION_REQUIRED" and cooldown_elapsed(zone["zone_id"]):
        alert = raise_alert(zone, decision, reading, forecast, "automatic")

    record_activity("sensor", {"kind": "sensor", "direction": "inbound", "provider": "API Gateway", "method": "POST",
                               "endpoint": f"/zones/{zone['zone_id']}/readings", "zone_id": zone["zone_id"],
                               "status": "success", "http_status": 201,
                               "summary": f"{device_id or 'sensor'} · moisture {moisture:.1f}% → {decision['recommendation']}"})
    return ok({"decision": decision, "reading_id": reading["reading_id"],
               "alert_id": alert["alert_id"] if alert else None,
               "alert": alert, "forecast_status": "available" if rain else "unavailable",
               "forecast_error": forecast_error}, 201)


def api_ingest(ev: "Req") -> Dict[str, Any]:
    return ingest(get_zone_or_404(ev.params["zone_id"]), ev.body)


def api_sensor_data(ev: "Req") -> Dict[str, Any]:
    """Prompt-style alias: {farmId, soilMoisture, temperature, humidity, latitude?, longitude?}.
    Unknown farms are created on first reading when coordinates are supplied."""
    b = ev.body
    farm_id = text(b, "farmId", 64)
    body = {"soil_moisture": b.get("soilMoisture"), "temperature": b.get("temperature"),
            "humidity": b.get("humidity"), "device_id": b.get("deviceId")}
    zone_id = slugify(farm_id)
    item = table("zones").get_item(Key={"zone_id": zone_id}).get("Item")
    if item:
        zone = from_dynamo(item)
    else:
        lat, lon = number(b, "latitude", -90, 90), number(b, "longitude", -180, 180)
        zone = create_zone_record({"name": farm_id, "latitude": lat, "longitude": lon, "crop_type": "unspecified",
                                   "soil_type": "unspecified", "moisture_threshold": DEFAULT_MOISTURE_THRESHOLD,
                                   "target_moisture": DEFAULT_MOISTURE_THRESHOLD + 15}, zone_id)
    return ingest(zone, body)


def api_list_readings(ev: "Req") -> Dict[str, Any]:
    get_zone_or_404(ev.params["zone_id"])
    try:
        hours = max(1, min(int(ev.query.get("hours", 72)), 168))
    except ValueError:
        raise ApiError(400, "VALIDATION_ERROR", "hours must be an integer.")
    start = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    resp = table("readings").query(KeyConditionExpression=Key("zone_id").eq(ev.params["zone_id"]) & Key("timestamp").gte(start))
    readings = [from_dynamo(i) for i in resp.get("Items", [])]
    return ok({"zone_id": ev.params["zone_id"], "hours": hours, "readings": readings, "count": len(readings)})


# ─── Decisions & alerts ─────────────────────────────────────────────────────

def api_list_decisions(ev: "Req") -> Dict[str, Any]:
    limit = int(ev.query.get("limit", 50)) if ev.query.get("limit", "50").isdigit() else 50
    if ev.query.get("zone_id"):
        resp = table("decisions").query(KeyConditionExpression=Key("zone_id").eq(ev.query["zone_id"]),
                                        ScanIndexForward=False, Limit=limit)
    else:
        resp = table("decisions").query(IndexName="AllDecisionsByTimeIndex", ScanIndexForward=False, Limit=limit,
                                        KeyConditionExpression=Key("record_type").eq("DECISION"))
    items = [from_dynamo(i) for i in resp.get("Items", [])]
    return ok({"decisions": items, "count": len(items)})


def api_latest_decision(ev: "Req") -> Dict[str, Any]:
    resp = table("decisions").query(KeyConditionExpression=Key("zone_id").eq(ev.params["zone_id"]),
                                    ScanIndexForward=False, Limit=1)
    items = resp.get("Items", [])
    return ok({"zone_id": ev.params["zone_id"], "decision": from_dynamo(items[0]) if items else None})


def api_list_alerts(ev: "Req") -> Dict[str, Any]:
    status, zone_id = ev.query.get("status"), ev.query.get("zone_id")
    if status and status not in ("active", "acknowledged"):
        raise ApiError(400, "VALIDATION_ERROR", "status must be 'active' or 'acknowledged'.")
    if status:
        resp = table("alerts").query(IndexName="StatusIndex", KeyConditionExpression=Key("status").eq(status),
                                     ScanIndexForward=False)
    elif zone_id:
        resp = table("alerts").query(IndexName="ZoneIndex", KeyConditionExpression=Key("zone_id").eq(zone_id),
                                     ScanIndexForward=False)
    else:
        resp = table("alerts").scan()
    items = [from_dynamo(i) for i in resp.get("Items", [])]
    if zone_id:
        items = [a for a in items if a["zone_id"] == zone_id]
    items.sort(key=lambda a: a["created_at"], reverse=True)
    return ok({"alerts": items, "count": len(items)})


def get_alert_or_404(alert_id: str) -> Dict[str, Any]:
    item = table("alerts").get_item(Key={"alert_id": alert_id}).get("Item")
    if not item:
        raise ApiError(404, "ALERT_NOT_FOUND", f"Alert '{alert_id}' does not exist.")
    return from_dynamo(item)


def api_get_alert(ev: "Req") -> Dict[str, Any]:
    return ok({"alert": get_alert_or_404(ev.params["alert_id"])})


def api_ack_alert(ev: "Req") -> Dict[str, Any]:
    alert = get_alert_or_404(ev.params["alert_id"])
    status = ev.body.get("status", "acknowledged")
    if status not in ("active", "acknowledged"):
        raise ApiError(400, "VALIDATION_ERROR", "status must be 'active' or 'acknowledged'.")
    alert["status"] = status
    alert["acknowledged_at"] = now_iso() if status == "acknowledged" else None
    table("alerts").put_item(Item=to_dynamo(alert))
    return ok({"alert": alert})


def api_trigger_alert(ev: "Req") -> Dict[str, Any]:
    """Manual alert: evaluate the zone now and email regardless of cooldown."""
    zone = get_zone_or_404(ev.params["zone_id"])
    resp = table("readings").query(KeyConditionExpression=Key("zone_id").eq(zone["zone_id"]), ScanIndexForward=False, Limit=1)
    if not resp.get("Items"):
        raise ApiError(400, "VALIDATION_ERROR", "This zone has no sensor readings yet.")
    reading = from_dynamo(resp["Items"][0])
    rain, forecast, forecast_error = forecast_for_decision(zone)
    decision = evaluate(zone, float(reading["soil_moisture"]), reading.get("temperature"), reading.get("humidity"),
                        rain, forecast_error, reading["reading_id"])
    table("decisions").put_item(Item=to_dynamo(decision))
    return ok({"alert": raise_alert(zone, decision, reading, forecast, "manual"), "decision": decision}, 201)


# ─── Subscribers ────────────────────────────────────────────────────────────

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def api_list_subscribers(ev: "Req") -> Dict[str, Any]:
    subs = [{**s, "email": mask_email(s["email"])} for s in list_subscribers()]
    return ok({"subscribers": subs, "count": len(subs)})


def api_create_subscriber(ev: "Req") -> Dict[str, Any]:
    name = text(ev.body, "name", 80)
    email = (text(ev.body, "email", 254) or "").lower()
    if not EMAIL_RE.match(email):
        raise ApiError(400, "VALIDATION_ERROR", "A valid email address is required.")
    zone_ids = ev.body.get("zone_ids") or ["*"]
    if not isinstance(zone_ids, list) or not all(isinstance(z, str) for z in zone_ids):
        raise ApiError(400, "VALIDATION_ERROR", "zone_ids must be a list of zone ids.")
    if any(s["email"] == email for s in list_subscribers()):
        raise ApiError(409, "ALREADY_REGISTERED", "This email address is already registered.")
    for zid in zone_ids:
        if zid != "*":
            get_zone_or_404(zid)

    sub = {"subscriber_id": new_id("sub"), "name": name, "email": email, "zone_ids": zone_ids,
           "active": True, "created_at": now_iso()}
    table("subscribers").put_item(Item=to_dynamo(sub))
    try:
        # In the SES sandbox, recipients must be verified: AWS emails them a confirmation link.
        _ses.verify_email_identity(EmailAddress=email)
    except (ClientError, BotoCoreError):
        logger.warning("Could not request SES verification for %s", mask_email(email), exc_info=True)
    welcome = send_email(email, "[AgriIoT] You're subscribed to irrigation alerts",
                         f"Hi {name},\n\nYou'll receive an email whenever AgriIoT recommends irrigation.\n\n— AgriIoT",
                         f"<p>Hi {html.escape(name)},</p><p>You'll receive an email whenever AgriIoT recommends irrigation.</p>",
                         None, "welcome")
    return ok({"subscriber": {**sub, "email": mask_email(email)}, "welcome_email": welcome}, 201)


def api_delete_subscriber(ev: "Req") -> Dict[str, Any]:
    resp = table("subscribers").delete_item(Key={"subscriber_id": ev.params["subscriber_id"]}, ReturnValues="ALL_OLD")
    if "Attributes" not in resp:
        raise ApiError(404, "NOT_FOUND", "Subscriber not found.")
    return ok({"deleted": ev.params["subscriber_id"]})


# ─── System status & activity ───────────────────────────────────────────────

def api_status(ev: "Req") -> Dict[str, Any]:
    key, sender = _env("OPENWEATHER_API_KEY"), _env("SES_SENDER_EMAIL")
    try:
        subscriber_count = len(list_subscribers())
    except (ClientError, BotoCoreError):
        subscriber_count = 0
    return ok({
        "environment": _env("APP_ENV", "aws"),
        "region": _env("AWS_REGION", "unknown"),
        "weather": {"provider": "openweather", "provider_name": "OpenWeatherMap One Call 3.0",
                    "endpoint": OPENWEATHER_URL, "api_key_configured": bool(key), "api_key_masked": mask(key),
                    "forecast_days": FORECAST_DAYS, "fallback": None},
        "sms": {"service": "Not used (alerts by email)", "mode": "aws", "topic_configured": False,
                "topic_name": None, "recipients": [], "cooldown_minutes": int(ALERT_COOLDOWN_MINUTES)},
        "email": {"service": "Amazon SES", "mode": "ses" if sender else "mock",
                  "sender": mask_email(sender) if sender else None, "subscribers": subscriber_count},
        "storage": {"service": "Amazon DynamoDB"},
    })


def api_activity(ev: "Req") -> Dict[str, Any]:
    stream = ev.query.get("stream", "weather")
    if stream not in ("weather", "sensor", "sms", "email"):
        raise ApiError(400, "VALIDATION_ERROR", "stream must be weather, sensor, sms or email.")
    limit = max(1, min(int(ev.query.get("limit", "50")) if ev.query.get("limit", "50").isdigit() else 50, 200))
    resp = table("activity").query(KeyConditionExpression=Key("stream").eq(stream), ScanIndexForward=False, Limit=limit)
    events = [from_dynamo(i) for i in resp.get("Items", [])]
    return ok({"stream": stream, "events": events, "count": len(events)})


# ─── Routing ────────────────────────────────────────────────────────────────

class Req:
    def __init__(self, method: str, path: str, params: Dict[str, str], query: Dict[str, str], body: Dict[str, Any]):
        self.method, self.path, self.params, self.query, self.body = method, path, params, query, body


ROUTES: List[Tuple[str, str, Callable[[Req], Dict[str, Any]]]] = [
    ("GET", "/zones", lambda ev: ok({"zones": (z := list_zones()), "count": len(z)})),
    ("POST", "/zones", api_create_zone),
    ("GET", "/zones/{zone_id}", lambda ev: ok({"zone": get_zone_or_404(ev.params["zone_id"])})),
    ("PUT", "/zones/{zone_id}", api_update_zone),
    ("DELETE", "/zones/{zone_id}", api_delete_zone),
    ("POST", "/zones/{zone_id}/readings", api_ingest),
    ("GET", "/zones/{zone_id}/readings", api_list_readings),
    ("GET", "/zones/{zone_id}/weather", api_get_weather),
    ("POST", "/zones/{zone_id}/weather/refresh", api_refresh_weather),
    ("GET", "/zones/{zone_id}/irrigation/latest", api_latest_decision),
    ("POST", "/zones/{zone_id}/alerts/trigger", api_trigger_alert),
    ("GET", "/irrigation/decisions", api_list_decisions),
    ("GET", "/alerts", api_list_alerts),
    ("GET", "/alerts/{alert_id}", api_get_alert),
    ("PATCH", "/alerts/{alert_id}", api_ack_alert),
    ("GET", "/subscribers", api_list_subscribers),
    ("POST", "/subscribers", api_create_subscriber),
    ("DELETE", "/subscribers/{subscriber_id}", api_delete_subscriber),
    ("GET", "/system/status", api_status),
    ("GET", "/system/activity", api_activity),
    ("POST", "/api/sensor-data", api_sensor_data),
]
_COMPILED = [(m, re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", p) + "/?$"), fn) for m, p, fn in ROUTES]


def _parse(event: Dict[str, Any]) -> Req:
    ctx = event.get("requestContext") or {}
    method = (event.get("httpMethod") or ctx.get("http", {}).get("method") or "GET").upper()
    path = event.get("rawPath") or event.get("path") or "/"
    stage = ctx.get("stage")
    if stage and stage != "$default" and path.startswith(f"/{stage}/"):
        path = path[len(stage) + 1:]  # HTTP API rawPath includes the stage
    raw = event.get("body")
    if raw and event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    body: Dict[str, Any] = {}
    if raw:
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            raise ApiError(400, "VALIDATION_ERROR", "Request body must be valid JSON.")
        if not isinstance(body, dict):
            raise ApiError(400, "VALIDATION_ERROR", "Request body must be a JSON object.")
    return Req(method, urllib.parse.unquote(path), {}, event.get("queryStringParameters") or {}, body)


def refresh_all_zones() -> Dict[str, str]:
    results = {}
    for zone in list_zones():
        if zone.get("enabled", True):
            try:
                results[zone["zone_id"]] = f"{len(refresh_forecast(zone))} days"
            except ApiError as exc:
                results[zone["zone_id"]] = f"failed: {exc.message}"
    logger.info("Scheduled forecast refresh: %s", results)
    return results


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    # EventBridge schedule → refresh every zone's forecast
    if event.get("source") == "aws.events" or event.get("detail-type") == "Scheduled Event":
        return {"refreshed": refresh_all_zones()}
    try:
        req = _parse(event)
        if req.method == "OPTIONS":
            return response(204, {})
        allowed = False
        for method, pattern, fn in _COMPILED:
            match = pattern.match(req.path)
            if match:
                allowed = True
                if method == req.method:
                    req.params = match.groupdict()
                    return fn(req)
        if allowed:
            raise ApiError(405, "METHOD_NOT_ALLOWED", f"{req.method} is not allowed on {req.path}.")
        raise ApiError(404, "NOT_FOUND", f"No route for {req.method} {req.path}.")
    except ApiError as exc:
        return response(exc.status, {"success": False, "error": {"code": exc.code, "message": exc.message}})
    except (ClientError, BotoCoreError):
        logger.exception("AWS service call failed")
        return response(502, {"success": False, "error": {"code": "SERVICE_UNAVAILABLE",
                                                           "message": "A backend AWS service failed. Check CloudWatch logs."}})
    except Exception:  # noqa: BLE001 — never leak a stack trace to the client
        logger.exception("Unhandled error")
        return response(500, {"success": False, "error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."}})
