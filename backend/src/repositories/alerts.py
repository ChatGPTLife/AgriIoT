"""
Alerts repository.

Table: Alerts (PK: alert_id)
  GSI ZoneIndex:   PK zone_id,  SK created_at  (per-zone history + cooldown lookup)
  GSI StatusIndex: PK status,   SK created_at  (active/acknowledged listing)
See docs/database.md for the full schema and access patterns.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from boto3.dynamodb.conditions import Key

from src.repositories.base import get_table
from src.utils.config import get_config
from src.utils.dynamo_serialization import from_dynamo, to_dynamo

ZONE_INDEX = "ZoneIndex"
STATUS_INDEX = "StatusIndex"


def _table():
    return get_table(get_config().alerts_table)


def create_alert(alert: Dict[str, Any]) -> Dict[str, Any]:
    _table().put_item(Item=to_dynamo(alert))
    return alert


def get_alert(alert_id: str) -> Optional[Dict[str, Any]]:
    resp = _table().get_item(Key={"alert_id": alert_id})
    item = resp.get("Item")
    return from_dynamo(item) if item else None


def get_latest_alert_for_zone(zone_id: str) -> Optional[Dict[str, Any]]:
    resp = _table().query(
        IndexName=ZONE_INDEX,
        KeyConditionExpression=Key("zone_id").eq(zone_id),
        ScanIndexForward=False,
        Limit=1,
    )
    items = resp.get("Items", [])
    return from_dynamo(items[0]) if items else None


def list_alerts(status: Optional[str] = None, zone_id: Optional[str] = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    table = _table()
    kwargs: Dict[str, Any] = {"ScanIndexForward": False}
    if limit:
        kwargs["Limit"] = limit

    if zone_id and status:
        kwargs["IndexName"] = ZONE_INDEX
        kwargs["KeyConditionExpression"] = Key("zone_id").eq(zone_id)
        kwargs["FilterExpression"] = "#s = :status"
        kwargs["ExpressionAttributeNames"] = {"#s": "status"}
        kwargs["ExpressionAttributeValues"] = {":status": status}
        resp = table.query(**kwargs)
    elif zone_id:
        kwargs["IndexName"] = ZONE_INDEX
        kwargs["KeyConditionExpression"] = Key("zone_id").eq(zone_id)
        resp = table.query(**kwargs)
    elif status:
        kwargs["IndexName"] = STATUS_INDEX
        kwargs["KeyConditionExpression"] = Key("status").eq(status)
        resp = table.query(**kwargs)
    else:
        # No index applies to "everything" — acceptable at MVP scale; see
        # docs/database.md for the scaling note and upgrade path.
        resp = table.scan()

    return [from_dynamo(i) for i in resp.get("Items", [])]


def update_alert_status(alert_id: str, status: str, acknowledged_at: Optional[str] = None) -> Dict[str, Any]:
    names = {"#s": "status"}
    values: Dict[str, Any] = {":status": status}
    expr = "SET #s = :status"
    if acknowledged_at:
        expr += ", acknowledged_at = :ack"
        values[":ack"] = acknowledged_at
    resp = _table().update_item(
        Key={"alert_id": alert_id},
        UpdateExpression=expr,
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=to_dynamo(values),
        ConditionExpression="attribute_exists(alert_id)",
        ReturnValues="ALL_NEW",
    )
    return from_dynamo(resp["Attributes"])
