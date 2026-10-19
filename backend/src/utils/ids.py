"""ID, slug, and timestamp helpers shared by services."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def utc_today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def slugify(text: str) -> str:
    slug = text.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or "zone"
