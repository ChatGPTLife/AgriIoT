from datetime import datetime, timedelta, timezone

import pytest
from botocore.exceptions import ClientError

from src.repositories import alerts as alerts_repo
from src.repositories import irrigation as irrigation_repo
from src.repositories import readings as readings_repo
from src.repositories import zones as zones_repo


def test_create_get_list_update_delete_zone(dynamodb_tables):
    zone = {
        "zone_id": "zone-a",
        "name": "Tomato Field",
        "latitude": 12.9,
        "longitude": 77.6,
        "crop_type": "Tomato",
        "soil_type": "Loamy",
        "moisture_threshold": 35.0,
        "target_moisture": 55.0,
        "enabled": True,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    zones_repo.create_zone(zone)

    fetched = zones_repo.get_zone("zone-a")
    assert fetched["name"] == "Tomato Field"
    # DynamoDB Decimals for whole numbers come back as `int` (35, not
    # 35.0) — Pydantic coerces int->float for float-typed model fields, so
    # this is a value check, not a strict-type check.
    assert fetched["moisture_threshold"] == 35.0

    with pytest.raises(ClientError) as exc_info:
        zones_repo.create_zone(zone)
    assert zones_repo.is_conditional_check_failure(exc_info.value)

    all_zones = zones_repo.list_zones()
    assert len(all_zones) == 1

    updated = zones_repo.update_zone("zone-a", {"enabled": False, "moisture_threshold": 40.0})
    assert updated["enabled"] is False
    assert updated["moisture_threshold"] == 40.0

    with pytest.raises(ClientError):
        zones_repo.update_zone("zone-does-not-exist", {"enabled": False})

    zones_repo.delete_zone("zone-a")
    assert zones_repo.get_zone("zone-a") is None
    with pytest.raises(ClientError):
        zones_repo.delete_zone("zone-a")


def test_readings_query_range_and_latest(dynamodb_tables):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(5):
        readings_repo.put_reading({
            "reading_id": f"reading-{i}",
            "zone_id": "zone-a",
            "soil_moisture": 20.0 + i,
            "temperature": 25.0,
            "humidity": 50.0,
            "device_id": "demo-device-01",
            "timestamp": (base + timedelta(hours=i)).isoformat(),
            "created_at": (base + timedelta(hours=i)).isoformat(),
        })

    latest = readings_repo.get_latest_reading("zone-a")
    assert latest["reading_id"] == "reading-4"

    all_readings = readings_repo.query_readings("zone-a")
    assert len(all_readings) == 5
    assert all_readings[0]["reading_id"] == "reading-4"  # newest first

    limited = readings_repo.query_readings("zone-a", limit=2)
    assert len(limited) == 2

    ranged = readings_repo.query_readings(
        "zone-a",
        start=base.isoformat(),
        end=(base + timedelta(hours=1)).isoformat(),
    )
    assert {r["reading_id"] for r in ranged} == {"reading-0", "reading-1"}

    assert readings_repo.get_latest_reading("zone-nonexistent") is None


def test_alert_cooldown_lookup_and_status_listing(dynamodb_tables):
    now = datetime.now(timezone.utc)
    alerts_repo.create_alert({
        "alert_id": "alert-1",
        "zone_id": "zone-a",
        "zone_name": "Tomato Field",
        "created_at": now.isoformat(),
        "status": "active",
        "urgency": "HIGH",
        "reason": "Soil moisture below threshold.",
        "soil_moisture": 24.0,
        "threshold": 35.0,
        "expected_rainfall_mm": 0.8,
        "rain_probability": 10.0,
    })

    latest = alerts_repo.get_latest_alert_for_zone("zone-a")
    assert latest["alert_id"] == "alert-1"
    assert alerts_repo.get_latest_alert_for_zone("zone-b") is None

    active = alerts_repo.list_alerts(status="active")
    assert len(active) == 1

    acknowledged = alerts_repo.update_alert_status("alert-1", "acknowledged", acknowledged_at=now.isoformat())
    assert acknowledged["status"] == "acknowledged"
    assert alerts_repo.list_alerts(status="active") == []
    assert len(alerts_repo.list_alerts(status="acknowledged")) == 1

    with pytest.raises(ClientError):
        alerts_repo.update_alert_status("alert-does-not-exist", "acknowledged")


def test_irrigation_decision_listing_by_zone_and_across_zones(dynamodb_tables):
    now = datetime.now(timezone.utc).isoformat()
    irrigation_repo.put_decision({
        "zone_id": "zone-a",
        "evaluated_at": now,
        "recommendation": "IRRIGATION_REQUIRED",
        "urgency": "HIGH",
        "reason": "test",
        "soil_moisture": 20.0,
        "moisture_threshold": 35.0,
        "target_moisture": 55.0,
    })
    irrigation_repo.put_decision({
        "zone_id": "zone-b",
        "evaluated_at": now,
        "recommendation": "NO_IRRIGATION_NEEDED",
        "urgency": "NONE",
        "reason": "test",
        "soil_moisture": 60.0,
        "moisture_threshold": 35.0,
        "target_moisture": 55.0,
    })

    for_zone_a = irrigation_repo.list_decisions(zone_id="zone-a")
    assert len(for_zone_a) == 1
    assert "record_type" not in for_zone_a[0]

    across_all = irrigation_repo.list_decisions()
    assert len(across_all) == 2

    required_only = irrigation_repo.list_decisions(status="IRRIGATION_REQUIRED")
    assert len(required_only) == 1
    assert required_only[0]["zone_id"] == "zone-a"
