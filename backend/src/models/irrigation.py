from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel


class Recommendation(str, Enum):
    NO_IRRIGATION_NEEDED = "NO_IRRIGATION_NEEDED"
    WAIT_FOR_RAIN = "WAIT_FOR_RAIN"
    IRRIGATION_REQUIRED = "IRRIGATION_REQUIRED"


class Urgency(str, Enum):
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class IrrigationDecision(BaseModel):
    zone_id: str
    evaluated_at: str
    recommendation: Recommendation
    urgency: Urgency
    reason: str
    soil_moisture: float
    moisture_threshold: float
    target_moisture: float
    temperature: Optional[float] = None
    humidity: Optional[float] = None
    forecast_rainfall_mm: Optional[float] = None
    rain_probability: Optional[float] = None
    reading_id: Optional[str] = None
