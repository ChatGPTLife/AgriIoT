from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class SensorReadingCreate(BaseModel):
    zone_id: str = Field(min_length=1)
    soil_moisture: float = Field(ge=0, le=100, description="Volumetric soil moisture, percent.")
    temperature: float = Field(ge=-40, le=70, description="Degrees Celsius.")
    humidity: float = Field(ge=0, le=100, description="Relative humidity, percent.")
    device_id: Optional[str] = Field(default=None, max_length=100)


class SensorReading(BaseModel):
    reading_id: str
    zone_id: str
    soil_moisture: float
    temperature: float
    humidity: float
    device_id: Optional[str] = None
    timestamp: str
    created_at: str
