"""
DynamoDB stores all numbers as `Decimal` and the boto3 resource API
rejects native Python `float` values on writes. These helpers convert
recursively at the boundary so the rest of the codebase (Pydantic models,
business logic) can use plain floats everywhere.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any


def to_dynamo(value: Any) -> Any:
    """Recursively convert floats to Decimal for storage."""
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: to_dynamo(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_dynamo(v) for v in value]
    return value


def from_dynamo(value: Any) -> Any:
    """Recursively convert Decimals back to int/float for application use."""
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    if isinstance(value, dict):
        return {k: from_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [from_dynamo(v) for v in value]
    return value
