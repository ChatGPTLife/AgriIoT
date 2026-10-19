"""
Email alert subscribers repository.

Table: Subscribers (PK: subscriber_id)
  zone_ids = ["*"] means "all zones".
The table is small (people, not readings), so zone matching is a Scan.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.repositories.base import get_table
from src.utils.config import get_config
from src.utils.dynamo_serialization import from_dynamo, to_dynamo

ALL_ZONES = "*"


def _table():
    return get_table(get_config().subscribers_table)


def put_subscriber(subscriber: Dict[str, Any]) -> Dict[str, Any]:
    _table().put_item(Item=to_dynamo(subscriber))
    return subscriber


def list_subscribers() -> List[Dict[str, Any]]:
    table = _table()
    resp = table.scan()
    items = resp.get("Items", [])
    while "LastEvaluatedKey" in resp:
        resp = table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
        items.extend(resp.get("Items", []))
    return sorted((from_dynamo(i) for i in items), key=lambda s: s.get("created_at", ""))


def find_by_email(email: str) -> Optional[Dict[str, Any]]:
    email = email.lower()
    return next((s for s in list_subscribers() if s.get("email") == email), None)


def subscribers_for_zone(zone_id: str) -> List[Dict[str, Any]]:
    return [
        s for s in list_subscribers()
        if s.get("active", True) and (ALL_ZONES in s.get("zone_ids", []) or zone_id in s.get("zone_ids", []))
    ]


def delete_subscriber(subscriber_id: str) -> bool:
    resp = _table().delete_item(Key={"subscriber_id": subscriber_id}, ReturnValues="ALL_OLD")
    return "Attributes" in resp
