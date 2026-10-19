from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, model_validator


class ZoneCreate(BaseModel):
    zone_id: Optional[str] = Field(
        default=None,
        max_length=64,
        description="Optional custom slug (e.g. 'zone-a'). Auto-generated from name if omitted.",
    )
    name: str = Field(min_length=1, max_length=100)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    crop_type: str = Field(min_length=1, max_length=100)
    soil_type: str = Field(min_length=1, max_length=100)
    moisture_threshold: float = Field(ge=0, le=100, description="Soil moisture % below which irrigation is considered.")
    target_moisture: float = Field(ge=0, le=100, description="Soil moisture % irrigation aims to restore.")
    enabled: bool = True

    @model_validator(mode="after")
    def _target_above_threshold(self) -> "ZoneCreate":
        if self.target_moisture <= self.moisture_threshold:
            raise ValueError("target_moisture must be greater than moisture_threshold")
        return self


class ZoneUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    crop_type: Optional[str] = Field(default=None, min_length=1, max_length=100)
    soil_type: Optional[str] = Field(default=None, min_length=1, max_length=100)
    moisture_threshold: Optional[float] = Field(default=None, ge=0, le=100)
    target_moisture: Optional[float] = Field(default=None, ge=0, le=100)
    enabled: Optional[bool] = None

    @model_validator(mode="after")
    def _target_above_threshold_if_both_present(self) -> "ZoneUpdate":
        if (
            self.target_moisture is not None
            and self.moisture_threshold is not None
            and self.target_moisture <= self.moisture_threshold
        ):
            raise ValueError("target_moisture must be greater than moisture_threshold")
        return self


class Zone(BaseModel):
    zone_id: str
    name: str
    latitude: float
    longitude: float
    crop_type: str
    soil_type: str
    moisture_threshold: float
    target_moisture: float
    enabled: bool
    created_at: str
    updated_at: str
