"""
Zones repository.

Table: Zones (PK: zone_id)
See docs/database.md for the full schema and access patterns.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from botocore.exceptions import ClientError

from src.repositories.base import get_table
from src.utils.config import get_config
from src.utils.dynamo_serialization import from_dynamo, to_dynamo


def _table():
    return get_table(get_config().zones_table)


def create_zone(zone: Dict[str, Any]) -> Dict[str, Any]:
    """Insert a new zone. Raises ClientError (ConditionalCheckFailedException)
    if zone_id already exists; callers translate this to a domain error."""
    _table().put_item(Item=to_dynamo(zone), ConditionExpression="attribute_not_exists(zone_id)")
    return zone


def get_zone(zone_id: str) -> Optional[Dict[str, Any]]:
    resp = _table().get_item(Key={"zone_id": zone_id})
    item = resp.get("Item")
    return from_dynamo(item) if item else None


def list_zones() -> List[Dict[str, Any]]:
    table = _table()
    items: List[Dict[str, Any]] = []
    resp = table.scan()
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
        items.extend(resp.get("Items", []))
    return [from_dynamo(i) for i in items]


def update_zone(zone_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    """Partial update. `updates` must be non-empty. Raises ClientError
    (ConditionalCheckFailedException) if the zone does not exist."""
    names = {f"#{k}": k for k in updates}
    values = {f":{k}": v for k, v in to_dynamo(updates).items()}
    expr = "SET " + ", ".join(f"#{k} = :{k}" for k in updates)
    resp = _table().update_item(
        Key={"zone_id": zone_id},
        UpdateExpression=expr,
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
        ConditionExpression="attribute_exists(zone_id)",
        ReturnValues="ALL_NEW",
    )
    return from_dynamo(resp["Attributes"])


def delete_zone(zone_id: str) -> None:
    """Raises ClientError (ConditionalCheckFailedException) if the zone
    does not exist."""
    _table().delete_item(Key={"zone_id": zone_id}, ConditionExpression="attribute_exists(zone_id)")


def is_conditional_check_failure(exc: ClientError) -> bool:
    return exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"
