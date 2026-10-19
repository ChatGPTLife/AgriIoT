from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class Alert(BaseModel):
    alert_id: str
    zone_id: str
    zone_name: str
    created_at: str
    status: str  # "active" | "acknowledged"
    urgency: str  # NONE | LOW | MEDIUM | HIGH
    reason: str
    soil_moisture: float
    threshold: float
    expected_rainfall_mm: float
    rain_probability: float
    acknowledged_at: Optional[str] = None
