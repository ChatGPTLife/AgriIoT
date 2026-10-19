"""
Helpers that record external API calls and SMS deliveries to the activity
log, so the dashboard can show exactly which upstream calls were made, with
which (masked) credential, and how they went.

Secrets are never stored: API keys and phone numbers are masked to their
last four characters before anything is written.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

import requests

from src.repositories import activity as activity_repo


def mask_secret(value: Optional[str], visible: int = 4) -> Optional[str]:
    if not value:
        return None
    return "•" * 6 + value[-visible:]


def mask_phone(phone: str) -> str:
    return phone[:3] + "•" * max(len(phone) - 7, 3) + phone[-4:]


def tracked_request(
    method: str,
    url: str,
    *,
    provider: str,
    api_key: Optional[str],
    zone_id: str,
    query_hint: str = "",
    **kwargs: Any,
) -> requests.Response:
    """Perform an HTTP request and record it to the "weather" activity stream.
    Exceptions from `requests` are recorded and then re-raised unchanged."""
    started = time.perf_counter()
    event: Dict[str, Any] = {
        "kind": "weather",
        "direction": "outbound",
        "provider": provider,
        "method": method.upper(),
        "endpoint": url + (f"?{query_hint}" if query_hint else ""),
        "api_key_masked": mask_secret(api_key),
        "zone_id": zone_id,
    }
    try:
        resp = requests.request(method, url, **kwargs)
    except requests.RequestException as exc:
        event.update(
            status="error",
            http_status=None,
            latency_ms=round((time.perf_counter() - started) * 1000),
            summary=f"{type(exc).__name__}: request failed",
        )
        activity_repo.record_event("weather", event)
        raise

    event.update(
        status="success" if resp.ok else "error",
        http_status=resp.status_code,
        latency_ms=round((time.perf_counter() - started) * 1000),
        response_bytes=len(resp.content or b""),
        summary=f"HTTP {resp.status_code} {resp.reason or ''}".strip(),
    )
    activity_repo.record_event("weather", event)
    return resp


def record_sensor_ingest(zone_id: str, device_id: Optional[str], recommendation: str, moisture: float) -> None:
    activity_repo.record_event(
        "sensor",
        {
            "kind": "sensor",
            "direction": "inbound",
            "provider": "API Gateway",
            "method": "POST",
            "endpoint": f"/zones/{zone_id}/readings",
            "zone_id": zone_id,
            "status": "success",
            "http_status": 201,
            "summary": f"{device_id or 'sensor'} · moisture {moisture:.1f}% → {recommendation}",
        },
    )


def record_sms(
    *,
    target: str,
    target_type: str,
    message: str,
    zone_id: str,
    delivery: str,
    message_id: Optional[str],
    status: str,
    error: Optional[str] = None,
) -> None:
    activity_repo.record_event(
        "sms",
        {
            "kind": "sms",
            "target": mask_phone(target) if target_type == "phone" else target.split(":")[-1],
            "target_type": target_type,
            "message": message,
            "zone_id": zone_id,
            "delivery": delivery,
            "message_id": message_id,
            "status": status,
            "error": error,
        },
    )
