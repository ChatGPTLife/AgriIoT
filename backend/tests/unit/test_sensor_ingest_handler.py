"""
Unit tests for the sensor_ingest Lambda handler.

Covers the full pipeline:
  parse → zone check → persist reading → irrigation engine →
  persist decision → SNS alert (when conditions met)

Uses moto for DynamoDB + SNS — no real AWS calls are made.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict

import pytest
from moto import mock_aws

# ── helpers ────────────────────────────────────────────────────────────────

def _api_event(zone_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Minimal API Gateway proxy integration event."""
    return {
        "httpMethod": "POST",
        "resource": "/zones/{zone_id}/readings",
        "pathParameters": {"zone_id": zone_id},
        "queryStringParameters": None,
        "body": json.dumps(body),
        "isBase64Encoded": False,
    }


def _seed_zone(config, zone_id: str = "test-zone", **overrides) -> Dict[str, Any]:
    """Insert a zone into the mocked DynamoDB table."""
    from src.repositories.zones import create_zone
    from src.utils.dynamo_serialization import to_dynamo
    from src.repositories.base import get_table

    zone = {
        "zone_id": zone_id,
        "name": "Test Zone",
        "latitude": 19.076,
        "longitude": 72.877,
        "crop_type": "wheat",
        "soil_type": "loamy",
        "moisture_threshold": 40.0,
        "target_moisture": 60.0,
        "enabled": True,
        "created_at": "2024-01-01T00:00:00+00:00",
        "updated_at": "2024-01-01T00:00:00+00:00",
        **overrides,
    }
    create_zone(zone)
    return zone


def _seed_weather(config, zone_id: str = "test-zone", days: int = 2) -> None:
    """Insert N forecast-day rows for a zone into the mocked weather cache table."""
    from src.repositories.weather import put_forecast_days

    rows = [
        {
            "zone_id": zone_id,
            "forecast_date": f"2024-05-{i + 1:02d}",
            "fetched_at": "2024-05-01T00:00:00+00:00",
            "temperature_min": 20.0,
            "temperature_max": 32.0,
            "humidity": 55.0,
            "precipitation_mm": 1.0,         # not significant (< 5 mm)
            "precipitation_probability": 20.0,  # low probability
            "condition": "clear",
            "provider": "openweather",
        }
        for i in range(days)
    ]
    put_forecast_days(zone_id, rows)


# ── fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def mocked_aws(dynamodb_tables):
    """Extend the dynamodb_tables fixture with a mocked SNS topic."""
    import boto3

    config = dynamodb_tables
    sns = boto3.client("sns", region_name=config.aws_region)
    sns.create_topic(Name="test-topic")
    yield config


# ── tests ──────────────────────────────────────────────────────────────────

class TestIngestReading:
    def test_returns_201_with_decision(self, mocked_aws):
        """Happy path: dry soil, no rain → IRRIGATION_REQUIRED, 201 response."""
        config = mocked_aws
        _seed_zone(config, moisture_threshold=40.0, target_moisture=60.0)

        from src.handlers.sensor_ingest import ingest_reading

        event = _api_event("test-zone", {
            "soil_moisture": 20.0,
            "temperature": 25.0,
            "humidity": 50.0,
        })
        resp = ingest_reading(event, None)

        assert resp["statusCode"] == 201
        body = json.loads(resp["body"])
        assert body["success"] is True
        assert body["decision"]["recommendation"] == "IRRIGATION_REQUIRED"
        assert body["reading_id"].startswith("rdg-")

    def test_no_irrigation_when_moisture_sufficient(self, mocked_aws):
        """Soil above threshold → NO_IRRIGATION_NEEDED."""
        config = mocked_aws
        _seed_zone(config, moisture_threshold=40.0, target_moisture=60.0)

        from src.handlers.sensor_ingest import ingest_reading

        event = _api_event("test-zone", {
            "soil_moisture": 75.0,
            "temperature": 22.0,
            "humidity": 60.0,
        })
        resp = ingest_reading(event, None)

        assert resp["statusCode"] == 201
        body = json.loads(resp["body"])
        assert body["decision"]["recommendation"] == "NO_IRRIGATION_NEEDED"
        assert body["alert_id"] is None

    def test_wait_for_rain_when_forecast_significant(self, mocked_aws):
        """Dry soil but significant rain expected → WAIT_FOR_RAIN."""
        import boto3
        config = mocked_aws

        _seed_zone(config, moisture_threshold=40.0, target_moisture=60.0)
        # Override weather cache with significant rain
        from src.repositories.weather import put_forecast_days
        put_forecast_days("test-zone", [
            {
                "zone_id": "test-zone",
                "forecast_date": "2024-05-01",
                "fetched_at": "2024-05-01T00:00:00+00:00",
                "temperature_min": 18.0,
                "temperature_max": 26.0,
                "humidity": 80.0,
                "precipitation_mm": 8.0,      # > RAIN_SIGNIFICANT_MM=5
                "precipitation_probability": 70.0,  # > threshold=50
                "condition": "rain",
                "provider": "openweather",
            },
            {
                "zone_id": "test-zone",
                "forecast_date": "2024-05-02",
                "fetched_at": "2024-05-01T00:00:00+00:00",
                "temperature_min": 17.0,
                "temperature_max": 24.0,
                "humidity": 85.0,
                "precipitation_mm": 3.0,
                "precipitation_probability": 60.0,
                "condition": "rain",
                "provider": "openweather",
            },
        ])

        from src.handlers.sensor_ingest import ingest_reading

        event = _api_event("test-zone", {
            "soil_moisture": 25.0,
            "temperature": 22.0,
            "humidity": 70.0,
        })
        resp = ingest_reading(event, None)

        body = json.loads(resp["body"])
        assert body["decision"]["recommendation"] == "WAIT_FOR_RAIN"

    def test_zone_not_found_returns_404(self, mocked_aws):
        """Ingesting for a non-existent zone → 404."""
        from src.handlers.sensor_ingest import ingest_reading

        event = _api_event("does-not-exist", {
            "soil_moisture": 30.0,
            "temperature": 25.0,
            "humidity": 50.0,
        })
        resp = ingest_reading(event, None)
        assert resp["statusCode"] == 404
        body = json.loads(resp["body"])
        assert body["error"]["code"] == "ZONE_NOT_FOUND"

    def test_disabled_zone_returns_409(self, mocked_aws):
        """Ingesting for a disabled zone → 409 ZONE_DISABLED."""
        config = mocked_aws
        _seed_zone(config, enabled=False)

        from src.handlers.sensor_ingest import ingest_reading

        event = _api_event("test-zone", {
            "soil_moisture": 30.0,
            "temperature": 25.0,
            "humidity": 50.0,
        })
        resp = ingest_reading(event, None)
        assert resp["statusCode"] == 409
        body = json.loads(resp["body"])
        assert body["error"]["code"] == "ZONE_DISABLED"

    def test_invalid_body_returns_400(self, mocked_aws):
        """Body with out-of-range values → 400 VALIDATION_ERROR."""
        config = mocked_aws
        _seed_zone(config)

        from src.handlers.sensor_ingest import ingest_reading

        event = _api_event("test-zone", {
            "soil_moisture": 999.0,   # > 100 — invalid
            "temperature": 25.0,
            "humidity": 50.0,
        })
        resp = ingest_reading(event, None)
        assert resp["statusCode"] == 400

    def test_alert_created_when_irrigation_required(self, mocked_aws):
        """IRRIGATION_REQUIRED with cooldown elapsed → alert record persisted."""
        config = mocked_aws
        _seed_zone(config, moisture_threshold=40.0, target_moisture=60.0)
        _seed_weather(config)

        from src.handlers.sensor_ingest import ingest_reading
        from src.repositories import alerts as alerts_repo

        event = _api_event("test-zone", {
            "soil_moisture": 10.0,    # far below threshold
            "temperature": 38.0,      # high temp → bumps urgency
            "humidity": 30.0,
        })
        resp = ingest_reading(event, None)
        body = json.loads(resp["body"])

        assert body["alert_id"] is not None
        assert body["alert_id"].startswith("alert-")

        # Verify the alert is in DynamoDB
        stored_alert = alerts_repo.get_alert(body["alert_id"])
        assert stored_alert is not None
        assert stored_alert["status"] == "active"
        assert stored_alert["urgency"] == "HIGH"

    def test_decision_persisted_to_dynamodb(self, mocked_aws):
        """Every ingest writes an irrigation decision to DynamoDB."""
        config = mocked_aws
        _seed_zone(config)

        from src.handlers.sensor_ingest import ingest_reading
        from src.repositories import irrigation as irrigation_repo

        event = _api_event("test-zone", {
            "soil_moisture": 50.0,
            "temperature": 22.0,
            "humidity": 55.0,
        })
        ingest_reading(event, None)

        decisions = irrigation_repo.list_decisions(zone_id="test-zone", limit=1)
        assert len(decisions) == 1
        assert decisions[0]["recommendation"] == "NO_IRRIGATION_NEEDED"

    def test_reading_persisted_to_dynamodb(self, mocked_aws):
        """Sensor reading is written to DynamoDB on every ingest."""
        config = mocked_aws
        _seed_zone(config)

        from src.handlers.sensor_ingest import ingest_reading
        from src.repositories import readings as readings_repo

        event = _api_event("test-zone", {
            "soil_moisture": 55.0,
            "temperature": 20.0,
            "humidity": 60.0,
            "device_id": "sensor-001",
        })
        resp = ingest_reading(event, None)
        body = json.loads(resp["body"])

        latest = readings_repo.get_latest_reading("test-zone")
        assert latest is not None
        assert latest["reading_id"] == body["reading_id"]
        assert latest["device_id"] == "sensor-001"
