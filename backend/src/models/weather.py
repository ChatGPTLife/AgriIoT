from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class ForecastDay(BaseModel):
    zone_id: str
    forecast_date: str  # YYYY-MM-DD, UTC
    fetched_at: str  # ISO 8601 timestamp of when this row was cached
    temperature_min: float
    temperature_max: float
    humidity: float
    precipitation_mm: float
    precipitation_probability: float  # 0-100
    condition: Optional[str] = None
    provider: str
