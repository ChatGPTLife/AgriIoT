"""
Alert emails over SMTP (Gmail by default).

Sender credentials come from SMTP_USER / SMTP_APP_PASSWORD. For Gmail this
is the sender's address plus a 16-character Google App Password (Google
Account → Security → 2-Step Verification → App passwords). Without them,
emails run in "mock" mode: they are printed to the server console and
recorded in the activity log as simulated, and nothing is sent.

Each recipient gets an individual message, so subscribers never see each
other's addresses.
"""
from __future__ import annotations

import html
import logging
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr
from typing import Any, Dict, List, Optional, Tuple

from src.repositories import activity as activity_repo
from src.utils.config import AppConfig, email_mode, get_config

logger = logging.getLogger(__name__)

REC_LABEL = {
    "IRRIGATION_REQUIRED": "Irrigation required",
    "WAIT_FOR_RAIN": "Hold irrigation — rain expected",
    "NO_IRRIGATION_NEEDED": "No irrigation needed",
}
REC_COLOR = {"IRRIGATION_REQUIRED": "#dc2626", "WAIT_FOR_RAIN": "#d97706", "NO_IRRIGATION_NEEDED": "#16a34a"}
COND_ICON = {
    "clear": "☀️", "partly_cloudy": "⛅", "cloudy": "☁️", "drizzle": "🌦", "light_rain": "🌦",
    "rain": "🌧", "heavy_rain": "⛈", "thunderstorm": "⛈", "snow": "❄️", "fog": "🌫",
}


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:2]}{'•' * max(len(local) - 2, 3)}@{domain}"


def _action_text(decision: Dict[str, Any], forecast_summary: Dict[str, float]) -> str:
    rec = decision.get("recommendation")
    if rec == "IRRIGATION_REQUIRED":
        return (f"Irrigate this zone to bring soil moisture back towards the target of "
                f"{decision.get('target_moisture', 0):.0f}%.")
    if rec == "WAIT_FOR_RAIN":
        return (f"Hold off irrigating: about {forecast_summary.get('expected_rainfall_mm', 0):.1f} mm of rain "
                f"is expected soon. Check again after the rain.")
    return "No action needed. Soil moisture is at or above the zone's threshold."


def _fmt_day(d: str) -> str:
    return datetime.fromisoformat(d).strftime("%a %d %b")


def build_alert_email(
    zone: Dict[str, Any],
    decision: Dict[str, Any],
    reading: Optional[Dict[str, Any]],
    forecast: List[Dict[str, Any]],
    forecast_summary: Dict[str, float],
    trigger: str,
) -> Tuple[str, str, str]:
    """Return (subject, plain_text, html) for an alert email."""
    rec = decision.get("recommendation", "NO_IRRIGATION_NEEDED")
    label = REC_LABEL.get(rec, rec)
    color = REC_COLOR.get(rec, "#52525b")
    name = zone.get("name", zone["zone_id"])
    urgency = decision.get("urgency", "NONE")
    prefix = "Manual alert" if trigger == "manual" else "Alert"
    subject = f"[AgriIoT] {prefix}: {label} — {name}" + (f" ({urgency})" if urgency != "NONE" else "")
    now = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    action = _action_text(decision, forecast_summary)

    moisture = decision.get("soil_moisture", 0.0)
    threshold = decision.get("moisture_threshold", 0.0)
    temp = decision.get("temperature")
    humidity = decision.get("humidity")
    rain2 = forecast_summary.get("expected_rainfall_mm", 0.0)
    prob2 = forecast_summary.get("rain_probability", 0.0)
    days = forecast[:5]

    lines = [
        f"{prefix.upper()}: {label}",
        f"Zone: {name} ({zone.get('crop_type', '')}, {zone.get('soil_type', '')})",
        f"Urgency: {urgency}",
        "",
        "SENSOR DATA",
        f"  Soil moisture: {moisture:.1f}% (threshold {threshold:.0f}%, target {decision.get('target_moisture', 0):.0f}%)",
        f"  Temperature:   {temp:.1f} °C" if temp is not None else "  Temperature:   —",
        f"  Humidity:      {humidity:.0f}%" if humidity is not None else "  Humidity:      —",
    ]
    if reading:
        lines.append(f"  Reading from {reading.get('device_id') or 'sensor'} at {reading.get('timestamp', '')[:16].replace('T', ' ')} UTC")
    lines += ["", f"WEATHER (next 2 days): {rain2:.1f} mm expected, up to {prob2:.0f}% chance of rain"]
    for d in days:
        lines.append(
            f"  {_fmt_day(d['forecast_date'])}: {d.get('condition', '').replace('_', ' ')}, "
            f"{d['temperature_max']:.0f}°/{d['temperature_min']:.0f}°, "
            f"{d['precipitation_mm']:.1f} mm ({d['precipitation_probability']:.0f}%)"
        )
    lines += ["", f"WHY: {decision.get('reason', '')}", f"WHAT TO DO: {action}", "", f"Sent {now} by AgriIoT."]
    text = "\n".join(lines)

    e = html.escape
    rows = "".join(
        f"<tr><td style='padding:6px 10px;border-top:1px solid #f0e6dc'>{_fmt_day(d['forecast_date'])}</td>"
        f"<td style='padding:6px 10px;border-top:1px solid #f0e6dc'>{COND_ICON.get(d.get('condition') or '', '🌡')} {e((d.get('condition') or '').replace('_', ' ').capitalize())}</td>"
        f"<td style='padding:6px 10px;border-top:1px solid #f0e6dc;text-align:right'>{d['temperature_max']:.0f}° / {d['temperature_min']:.0f}°</td>"
        f"<td style='padding:6px 10px;border-top:1px solid #f0e6dc;text-align:right'>{d['precipitation_mm']:.1f} mm</td>"
        f"<td style='padding:6px 10px;border-top:1px solid #f0e6dc;text-align:right'>{d['precipitation_probability']:.0f}%</td></tr>"
        for d in days
    ) or "<tr><td colspan='5' style='padding:8px 10px;color:#94877d'>No forecast cached yet.</td></tr>"

    def stat(label_: str, value: str) -> str:
        return (f"<td style='padding:12px;background:#f7efe6;border-radius:10px;text-align:center;width:25%'>"
                f"<div style='font-size:12px;color:#94877d'>{label_}</div>"
                f"<div style='font-size:18px;font-weight:600;color:#1f1a17;margin-top:2px'>{value}</div></td>")

    html_body = f"""<!doctype html><html><body style="margin:0;background:#f3eee8;font-family:Segoe UI,Helvetica,Arial,sans-serif;color:#1f1a17">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="padding:24px 12px"><tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;background:#ffffff;border-radius:18px;overflow:hidden">
  <tr><td style="background:#eb6e4b;color:#fff;padding:18px 24px;font-size:15px;font-weight:600">🌱 AgriIoT · {e(prefix)}</td></tr>
  <tr><td style="padding:24px">
    <div style="display:inline-block;padding:4px 10px;border-radius:999px;background:{color}1a;color:{color};font-size:12px;font-weight:700">{e(label.upper())}{' · ' + e(urgency) if urgency != 'NONE' else ''}</div>
    <h1 style="font-size:22px;margin:12px 0 4px">{e(name)}</h1>
    <div style="color:#5f544c;font-size:14px">{e(zone.get('crop_type', '').capitalize())} · {e(zone.get('soil_type', '').capitalize())} · {zone.get('latitude', 0):.4f}, {zone.get('longitude', 0):.4f}</div>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="6" style="margin:18px -6px 6px"><tr>
      {stat('Soil moisture', f'{moisture:.1f}%')}{stat('Threshold', f'{threshold:.0f}%')}
      {stat('Temperature', f'{temp:.1f}°C' if temp is not None else '—')}{stat('Humidity', f'{humidity:.0f}%' if humidity is not None else '—')}
    </tr></table>
    <p style="font-size:14px;line-height:1.55;margin:16px 0 6px"><b>What to do:</b> {e(action)}</p>
    <p style="font-size:13px;line-height:1.55;color:#5f544c;margin:0 0 18px"><b>Why:</b> {e(decision.get('reason', ''))}</p>
    <div style="font-size:14px;font-weight:600;margin-bottom:6px">Weather forecast</div>
    <div style="font-size:13px;color:#5f544c;margin-bottom:8px">Next 2 days: {rain2:.1f} mm expected, up to {prob2:.0f}% chance of rain</div>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="font-size:13px;border:1px solid #f0e6dc;border-radius:10px">
      <tr style="color:#94877d;font-size:12px"><td style="padding:6px 10px">Day</td><td style="padding:6px 10px">Conditions</td><td style="padding:6px 10px;text-align:right">High / Low</td><td style="padding:6px 10px;text-align:right">Rain</td><td style="padding:6px 10px;text-align:right">Chance</td></tr>
      {rows}
    </table>
  </td></tr>
  <tr><td style="padding:14px 24px;background:#fbf7f3;color:#94877d;font-size:12px">Sent {e(now)} · You receive this because your address is registered for AgriIoT irrigation alerts.</td></tr>
</table></td></tr></table></body></html>"""
    return subject, text, html_body


def send_email(to: str, subject: str, text: str, html_body: str, *, zone_id: Optional[str], kind: str,
               config: AppConfig | None = None) -> Dict[str, Any]:
    """Send one email (or simulate it) and record it to the "email" activity stream."""
    config = config or get_config()
    mode = email_mode(config)
    status, error = "sent", None

    if mode == "smtp":
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = formataddr((config.email_from_name, config.smtp_user))
        msg["To"] = to
        msg.set_content(text)
        msg.add_alternative(html_body, subtype="html")
        try:
            with smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=15) as smtp:
                smtp.login(config.smtp_user, config.smtp_app_password)
                smtp.send_message(msg)
            logger.info("Email sent to %s (%s)", mask_email(to), subject)
        except (smtplib.SMTPException, OSError) as exc:
            status, error = "failed", type(exc).__name__
            logger.warning("Email to %s failed: %s", mask_email(to), exc)
    else:
        status = "simulated"
        bar = "=" * 64
        print(f"\n{bar}\n  EMAIL (simulated, no SMTP credentials) -> {to}\n  Subject: {subject}\n{bar}\n{text}\n{bar}\n", flush=True)

    event = activity_repo.record_event("email", {
        "kind": kind,
        "target": mask_email(to),
        "subject": subject,
        "message": text,
        "zone_id": zone_id,
        "delivery": mode,
        "status": status,
        "error": error,
    })
    return {"to": mask_email(to), "status": status, "error": error, "event_id": event["event_id"]}


def send_welcome_email(subscriber: Dict[str, Any], zone_names: List[str]) -> Dict[str, Any]:
    zones = ", ".join(zone_names) if zone_names else "all zones"
    subject = "[AgriIoT] You're subscribed to irrigation alerts"
    text = (f"Hi {subscriber['name']},\n\nYou'll now get an email whenever AgriIoT decides a field needs attention.\n"
            f"Zones: {zones}\n\nEach alert includes the latest sensor reading, the weather forecast and what to do.\n\n— AgriIoT")
    html_body = (f"<div style='font-family:Segoe UI,Helvetica,Arial,sans-serif;max-width:520px;margin:auto;padding:24px;"
                 f"background:#fff;border-radius:16px;color:#1f1a17'><div style='color:#eb6e4b;font-weight:700'>🌱 AgriIoT</div>"
                 f"<h2 style='margin:10px 0'>Hi {html.escape(subscriber['name'])}, you're subscribed</h2>"
                 f"<p>You'll get an email whenever a field needs attention.</p><p><b>Zones:</b> {html.escape(zones)}</p>"
                 f"<p style='color:#5f544c'>Each alert includes the latest sensor reading, the 7-day weather forecast and what to do next.</p></div>")
    return send_email(subscriber["email"], subject, text, html_body, zone_id=None, kind="welcome")
