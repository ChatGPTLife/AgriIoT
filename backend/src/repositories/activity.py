"""
API activity log repository.

Table: ApiActivity (PK: stream [S], SK: created_at [ISO 8601])
  stream = "weather" — outbound weather API calls
  stream = "sensor" — inbound sensor reading ingests
  stream = "sms" — every SNS publish (topic or direct SMS)
  stream = "email" — every alert / welcome email (SMTP or simulated)
Items expire after ACTIVITY_TTL_DAYS via the `expires_at` TTL attribute.

Writes are best-effort: a logging failure must never break the request
that is being logged.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List

from boto3.dynamodb.conditions import Key

from src.repositories.base import get_table
from src.utils.config import get_config
from src.utils.dynamo_serialization import from_dynamo, to_dynamo
from src.utils.ids import new_id, utc_now_iso

logger = logging.getLogger(__name__)

ACTIVITY_TTL_DAYS = 7
STREAMS = ("weather", "sensor", "sms", "email")


def _table():
    return get_table(get_config().activity_table)


def record_event(stream: str, event: Dict[str, Any]) -> Dict[str, Any]:
    item = {
        "event_id": new_id("evt"),
        "stream": stream,
        "created_at": utc_now_iso(),
        "expires_at": int(time.time()) + ACTIVITY_TTL_DAYS * 86400,
        **event,
    }
    try:
        _table().put_item(Item=to_dynamo(item))
    except Exception:  # pylint: disable=broad-except
        logger.warning("Could not record %s activity event", stream, exc_info=True)
    return item


def list_events(stream: str, limit: int = 50) -> List[Dict[str, Any]]:
    resp = _table().query(
        KeyConditionExpression=Key("stream").eq(stream),
        ScanIndexForward=False,
        Limit=limit,
    )
    return [from_dynamo(i) for i in resp.get("Items", [])]
