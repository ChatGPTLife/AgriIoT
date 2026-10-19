from __future__ import annotations

from typing import Any, Dict, List

from botocore.exceptions import ClientError

from src.models.zone import ZoneCreate, ZoneUpdate
from src.repositories import zones as zones_repo
from src.utils.errors import ZoneAlreadyExistsError, ZoneNotFoundError
from src.utils.ids import slugify, utc_now_iso


def _unique_zone_id(desired: str) -> str:
    candidate = desired
    suffix = 2
    while zones_repo.get_zone(candidate) is not None:
        candidate = f"{desired}-{suffix}"
        suffix += 1
    return candidate


def create_zone(payload: ZoneCreate) -> Dict[str, Any]:
    now = utc_now_iso()
    zone_id = payload.zone_id or _unique_zone_id(slugify(payload.name))

    zone = {
        "zone_id": zone_id,
        "name": payload.name,
        "latitude": payload.latitude,
        "longitude": payload.longitude,
        "crop_type": payload.crop_type,
        "soil_type": payload.soil_type,
        "moisture_threshold": payload.moisture_threshold,
        "target_moisture": payload.target_moisture,
        "enabled": payload.enabled,
        "created_at": now,
        "updated_at": now,
    }
    try:
        zones_repo.create_zone(zone)
    except ClientError as exc:
        if zones_repo.is_conditional_check_failure(exc):
            raise ZoneAlreadyExistsError(zone_id) from exc
        raise
    return zone


def get_zone_or_raise(zone_id: str) -> Dict[str, Any]:
    zone = zones_repo.get_zone(zone_id)
    if zone is None:
        raise ZoneNotFoundError(zone_id)
    return zone


def list_zones() -> List[Dict[str, Any]]:
    return zones_repo.list_zones()


def update_zone(zone_id: str, payload: ZoneUpdate) -> Dict[str, Any]:
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        return get_zone_or_raise(zone_id)
    updates["updated_at"] = utc_now_iso()
    try:
        return zones_repo.update_zone(zone_id, updates)
    except ClientError as exc:
        if zones_repo.is_conditional_check_failure(exc):
            raise ZoneNotFoundError(zone_id) from exc
        raise


def delete_zone(zone_id: str) -> None:
    try:
        zones_repo.delete_zone(zone_id)
    except ClientError as exc:
        if zones_repo.is_conditional_check_failure(exc):
            raise ZoneNotFoundError(zone_id) from exc
        raise
