"""
Shared DynamoDB access. A fresh resource is created per call rather than
cached at module scope — this keeps behavior correct and simple under
moto-based tests (a cached client created outside a mock context would
otherwise leak across tests) at a negligible per-invocation cost.
"""
from __future__ import annotations

import boto3

from src.utils.config import get_config


def get_dynamodb_resource():
    config = get_config()
    kwargs = {"region_name": config.aws_region}
    if config.dynamodb_endpoint_url:
        kwargs["endpoint_url"] = config.dynamodb_endpoint_url
    return boto3.resource("dynamodb", **kwargs)


def get_table(table_name: str):
    return get_dynamodb_resource().Table(table_name)
