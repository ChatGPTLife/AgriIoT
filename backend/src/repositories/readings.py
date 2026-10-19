"""
Sensor readings repository.

Table: SensorReadings (PK: zone_id, SK: timestamp [ISO 8601])
See docs/database.md for the full schema and access patterns.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from boto3.dynamodb.conditions import Key

from src.repositories.base import get_table
from src.utils.config import get_config
from src.utils.dynamo_serialization import from_dynamo, to_dynamo


def _table():
    return get_table(get_config().readings_table)


def put_reading(reading: Dict[str, Any]) -> Dict[str, Any]:
    _table().put_item(Item=to_dynamo(reading))
    return reading


def query_readings(
    zone_id: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Readings for a zone, newest first, optionally bounded by an ISO 8601
    [start, end] timestamp range."""
    if start and end:
        key_cond = Key("zone_id").eq(zone_id) & Key("timestamp").between(start, end)
    elif start:
        key_cond = Key("zone_id").eq(zone_id) & Key("timestamp").gte(start)
    elif end:
        key_cond = Key("zone_id").eq(zone_id) & Key("timestamp").lte(end)
    else:
        key_cond = Key("zone_id").eq(zone_id)

    kwargs: Dict[str, Any] = {"KeyConditionExpression": key_cond, "ScanIndexForward": False}
    if limit:
        kwargs["Limit"] = limit

    resp = _table().query(**kwargs)
    return [from_dynamo(i) for i in resp.get("Items", [])]


def get_latest_reading(zone_id: str) -> Optional[Dict[str, Any]]:
    resp = _table().query(
        KeyConditionExpression=Key("zone_id").eq(zone_id),
        ScanIndexForward=False,
        Limit=1,
    )
    items = resp.get("Items", [])
    return from_dynamo(items[0]) if items else None


def get_latest_reading_per_zone(zone_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """Convenience for the dashboard summary: latest reading for each of
    the given zones, keyed by zone_id. Zones with no readings are omitted."""
    result: Dict[str, Dict[str, Any]] = {}
    for zone_id in zone_ids:
        latest = get_latest_reading(zone_id)
        if latest:
            result[zone_id] = latest
    return result
