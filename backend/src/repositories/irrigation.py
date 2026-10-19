"""
Irrigation decision history repository.

Table: IrrigationDecisions (PK: zone_id, SK: evaluated_at [ISO 8601])
  GSI AllDecisionsByTimeIndex: PK record_type (constant "DECISION"), SK evaluated_at
    -- a standard DynamoDB "fan-out" pattern so GET /irrigation/decisions
    can list across all zones in time order without a table Scan.
See docs/database.md for the full schema and access patterns.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from boto3.dynamodb.conditions import Key

from src.repositories.base import get_table
from src.utils.config import get_config
from src.utils.dynamo_serialization import from_dynamo, to_dynamo

ALL_DECISIONS_INDEX = "AllDecisionsByTimeIndex"
RECORD_TYPE = "DECISION"


def put_decision(decision: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(decision)
    item["record_type"] = RECORD_TYPE
    _table().put_item(Item=to_dynamo(item))
    return decision


def _table():
    return get_table(get_config().irrigation_decisions_table)


def list_decisions(
    zone_id: Optional[str] = None,
    status: Optional[str] = None,
    date: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """`status` filters on the `recommendation` field (kept as `status` in
    the query param per spec section 12); `date` filters to a single
    YYYY-MM-DD day via a prefix match on evaluated_at."""
    table = _table()
    kwargs: Dict[str, Any] = {"ScanIndexForward": False}
    if limit:
        kwargs["Limit"] = limit

    filters = []
    names: Dict[str, str] = {}
    values: Dict[str, Any] = {}
    if status:
        filters.append("#rec = :rec")
        names["#rec"] = "recommendation"
        values[":rec"] = status
    if date:
        filters.append("begins_with(evaluated_at, :date)")
        values[":date"] = date

    if zone_id:
        kwargs["KeyConditionExpression"] = Key("zone_id").eq(zone_id)
    else:
        kwargs["IndexName"] = ALL_DECISIONS_INDEX
        kwargs["KeyConditionExpression"] = Key("record_type").eq(RECORD_TYPE)

    if filters:
        kwargs["FilterExpression"] = " AND ".join(filters)
        kwargs["ExpressionAttributeNames"] = names
        kwargs["ExpressionAttributeValues"] = values

    resp = table.query(**kwargs)
    items = [from_dynamo(i) for i in resp.get("Items", [])]
    for item in items:
        item.pop("record_type", None)
    return items
