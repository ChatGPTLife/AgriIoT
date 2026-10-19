import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Safe defaults so importing src.utils.config never depends on the real
# environment. Individual tests override specific variables as needed via
# monkeypatch + reset_config_cache().
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("APP_ENV", "test")
# moto needs *some* credentials present, even though it never makes a real
# call — these are dummy placeholders, never real credentials.
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
os.environ.setdefault("OPENWEATHER_API_KEY", "test-key")
os.environ.setdefault("SNS_TOPIC_ARN", "arn:aws:sns:us-east-1:123456789012:test-topic")

import pytest  # noqa: E402
from moto import mock_aws  # noqa: E402


@pytest.fixture
def dynamodb_tables():
    """Spin up an in-memory DynamoDB (via moto) with tables/GSIs matching
    infrastructure/template.yaml, for the duration of one test."""
    with mock_aws():
        import boto3

        from src.utils.config import get_config, reset_config_cache

        reset_config_cache()
        config = get_config()
        client = boto3.client("dynamodb", region_name=config.aws_region)

        client.create_table(
            TableName=config.zones_table,
            AttributeDefinitions=[{"AttributeName": "zone_id", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "zone_id", "KeyType": "HASH"}],
            BillingMode="PAY_PER_REQUEST",
        )

        client.create_table(
            TableName=config.readings_table,
            AttributeDefinitions=[
                {"AttributeName": "zone_id", "AttributeType": "S"},
                {"AttributeName": "timestamp", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "zone_id", "KeyType": "HASH"},
                {"AttributeName": "timestamp", "KeyType": "RANGE"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        client.create_table(
            TableName=config.weather_cache_table,
            AttributeDefinitions=[
                {"AttributeName": "zone_id", "AttributeType": "S"},
                {"AttributeName": "forecast_date", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "zone_id", "KeyType": "HASH"},
                {"AttributeName": "forecast_date", "KeyType": "RANGE"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        client.create_table(
            TableName=config.alerts_table,
            AttributeDefinitions=[
                {"AttributeName": "alert_id", "AttributeType": "S"},
                {"AttributeName": "zone_id", "AttributeType": "S"},
                {"AttributeName": "created_at", "AttributeType": "S"},
                {"AttributeName": "status", "AttributeType": "S"},
            ],
            KeySchema=[{"AttributeName": "alert_id", "KeyType": "HASH"}],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "ZoneIndex",
                    "KeySchema": [
                        {"AttributeName": "zone_id", "KeyType": "HASH"},
                        {"AttributeName": "created_at", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": "StatusIndex",
                    "KeySchema": [
                        {"AttributeName": "status", "KeyType": "HASH"},
                        {"AttributeName": "created_at", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        client.create_table(
            TableName=config.irrigation_decisions_table,
            AttributeDefinitions=[
                {"AttributeName": "zone_id", "AttributeType": "S"},
                {"AttributeName": "evaluated_at", "AttributeType": "S"},
                {"AttributeName": "record_type", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "zone_id", "KeyType": "HASH"},
                {"AttributeName": "evaluated_at", "KeyType": "RANGE"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "AllDecisionsByTimeIndex",
                    "KeySchema": [
                        {"AttributeName": "record_type", "KeyType": "HASH"},
                        {"AttributeName": "evaluated_at", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        client.create_table(
            TableName=config.subscribers_table,
            AttributeDefinitions=[{"AttributeName": "subscriber_id", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "subscriber_id", "KeyType": "HASH"}],
            BillingMode="PAY_PER_REQUEST",
        )

        yield config
