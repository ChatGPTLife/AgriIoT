"""
Deterministic irrigation decision engine.

No machine learning is used anywhere in this module, by design: every
decision must be explainable purely from its inputs and the configured
thresholds. See docs/architecture.md for the full rationale and
docs/project-flow.md for worked examples.

Decision logic
--------------
1. soil_moisture >= moisture_threshold        -> NO_IRRIGATION_NEEDED
2. soil_moisture <  moisture_threshold
   AND significant rainfall is expected       -> WAIT_FOR_RAIN
3. soil_moisture <  moisture_threshold
   AND rainfall is unlikely/insufficient       -> IRRIGATION_REQUIRED

"Significant rainfall" means forecast rainfall over the configured
window is at least `rain_significant_mm` AND the rain probability is at
least `rain_probability_threshold_pct`. Both must hold — a high-probability
drizzle does not defer irrigation, and a large-but-unlikely storm does not
either.

Urgency scales with how far soil moisture sits below the threshold, and is
bumped up a level when temperature is high enough to meaningfully raise
evapotranspiration.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.models.irrigation import IrrigationDecision, Recommendation, Urgency
from src.utils.config import AppConfig, get_config
from src.utils.ids import utc_now_iso

# Deficit (percentage points below threshold) bands for urgency, before any
# temperature adjustment.
_HIGH_DEFICIT_PCT = 15.0
_MEDIUM_DEFICIT_PCT = 7.0

_URGENCY_BUMP = {
    Urgency.LOW: Urgency.MEDIUM,
    Urgency.MEDIUM: Urgency.HIGH,
    Urgency.HIGH: Urgency.HIGH,
    Urgency.NONE: Urgency.NONE,
}


@dataclass(frozen=True)
class IrrigationInputs:
    zone_id: str
    soil_moisture: float
    moisture_threshold: float
    target_moisture: float
    temperature: Optional[float] = None
    humidity: Optional[float] = None
    forecast_rainfall_mm: Optional[float] = None
    rain_probability: Optional[float] = None
    crop_type: Optional[str] = None
    soil_type: Optional[str] = None
    reading_id: Optional[str] = None


def _deficit_urgency(deficit_pct: float) -> Urgency:
    if deficit_pct >= _HIGH_DEFICIT_PCT:
        return Urgency.HIGH
    if deficit_pct >= _MEDIUM_DEFICIT_PCT:
        return Urgency.MEDIUM
    return Urgency.LOW


def _apply_temperature_bump(urgency: Urgency, temperature: Optional[float], config: AppConfig) -> Urgency:
    if temperature is not None and temperature >= config.high_temperature_c:
        return _URGENCY_BUMP[urgency]
    return urgency


def _is_significant_rain(rainfall_mm: float, probability_pct: float, config: AppConfig) -> bool:
    return rainfall_mm >= config.rain_significant_mm and probability_pct >= config.rain_probability_threshold_pct


def evaluate(inputs: IrrigationInputs, config: Optional[AppConfig] = None) -> IrrigationDecision:
    """Evaluate one zone's current conditions and forecast and return an
    IrrigationDecision. Pure function of its inputs plus configuration —
    no I/O, no side effects, fully unit-testable."""
    config = config or get_config()
    now = utc_now_iso()

    common = dict(
        zone_id=inputs.zone_id,
        evaluated_at=now,
        soil_moisture=inputs.soil_moisture,
        moisture_threshold=inputs.moisture_threshold,
        target_moisture=inputs.target_moisture,
        temperature=inputs.temperature,
        humidity=inputs.humidity,
        forecast_rainfall_mm=inputs.forecast_rainfall_mm,
        rain_probability=inputs.rain_probability,
        reading_id=inputs.reading_id,
    )

    if inputs.soil_moisture >= inputs.moisture_threshold:
        return IrrigationDecision(
            **common,
            recommendation=Recommendation.NO_IRRIGATION_NEEDED,
            urgency=Urgency.NONE,
            reason=(
                f"Soil moisture ({inputs.soil_moisture:.1f}%) is at or above the configured "
                f"threshold ({inputs.moisture_threshold:.1f}%) for this zone."
            ),
        )

    deficit = inputs.moisture_threshold - inputs.soil_moisture
    rainfall = inputs.forecast_rainfall_mm or 0.0
    probability = inputs.rain_probability or 0.0

    if _is_significant_rain(rainfall, probability, config):
        urgency = Urgency.LOW if deficit < _MEDIUM_DEFICIT_PCT else Urgency.MEDIUM
        return IrrigationDecision(
            **common,
            recommendation=Recommendation.WAIT_FOR_RAIN,
            urgency=urgency,
            reason=(
                f"Soil moisture ({inputs.soil_moisture:.1f}%) is below the threshold "
                f"({inputs.moisture_threshold:.1f}%), but {rainfall:.1f} mm of rain is expected "
                f"with a {probability:.0f}% probability within the next "
                f"{config.forecast_window_days_for_rain} day(s), so irrigation is being held off."
            ),
        )

    urgency = _apply_temperature_bump(_deficit_urgency(deficit), inputs.temperature, config)
    reason = (
        f"Soil moisture ({inputs.soil_moisture:.1f}%) is below the configured threshold "
        f"({inputs.moisture_threshold:.1f}%) and significant rainfall is not expected "
        f"during the forecast window."
    )
    if inputs.temperature is not None and inputs.temperature >= config.high_temperature_c:
        reason += f" High temperature ({inputs.temperature:.1f}°C) increases urgency."

    return IrrigationDecision(
        **common,
        recommendation=Recommendation.IRRIGATION_REQUIRED,
        urgency=urgency,
        reason=reason,
    )
