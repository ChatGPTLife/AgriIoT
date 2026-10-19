from src.models.irrigation import Recommendation, Urgency
from src.services.irrigation_engine import IrrigationInputs, evaluate
from src.utils.config import AppConfig

CONFIG = AppConfig(
    rain_significant_mm=5.0,
    rain_probability_threshold_pct=50.0,
    high_temperature_c=32.0,
    forecast_window_days_for_rain=2,
)


def _inputs(**overrides):
    base = dict(
        zone_id="zone-a",
        soil_moisture=24.0,
        moisture_threshold=35.0,
        target_moisture=55.0,
        temperature=28.0,
        humidity=60.0,
        forecast_rainfall_mm=0.0,
        rain_probability=0.0,
    )
    base.update(overrides)
    return IrrigationInputs(**base)


def test_moisture_above_threshold_needs_no_irrigation():
    decision = evaluate(_inputs(soil_moisture=60), config=CONFIG)
    assert decision.recommendation == Recommendation.NO_IRRIGATION_NEEDED
    assert decision.urgency == Urgency.NONE
    assert "60.0%" in decision.reason


def test_moisture_exactly_at_threshold_needs_no_irrigation():
    decision = evaluate(_inputs(soil_moisture=35, moisture_threshold=35), config=CONFIG)
    assert decision.recommendation == Recommendation.NO_IRRIGATION_NEEDED


def test_low_moisture_with_heavy_likely_rain_waits():
    decision = evaluate(_inputs(soil_moisture=24, forecast_rainfall_mm=12.0, rain_probability=80.0), config=CONFIG)
    assert decision.recommendation == Recommendation.WAIT_FOR_RAIN
    assert "12.0 mm" in decision.reason


def test_low_moisture_no_rain_requires_irrigation():
    decision = evaluate(_inputs(soil_moisture=24, forecast_rainfall_mm=0.5, rain_probability=10.0), config=CONFIG)
    assert decision.recommendation == Recommendation.IRRIGATION_REQUIRED


def test_high_probability_but_insignificant_rainfall_still_irrigates():
    # 90% probability of only 1mm of rain shouldn't be enough to hold off.
    decision = evaluate(_inputs(soil_moisture=20, forecast_rainfall_mm=1.0, rain_probability=90.0), config=CONFIG)
    assert decision.recommendation == Recommendation.IRRIGATION_REQUIRED


def test_large_but_unlikely_rainfall_still_irrigates():
    # 20mm forecast but only 15% chance shouldn't be enough to hold off.
    decision = evaluate(_inputs(soil_moisture=20, forecast_rainfall_mm=20.0, rain_probability=15.0), config=CONFIG)
    assert decision.recommendation == Recommendation.IRRIGATION_REQUIRED


def test_urgency_scales_with_deficit():
    low = evaluate(_inputs(soil_moisture=30, moisture_threshold=35, temperature=20), config=CONFIG)
    medium = evaluate(_inputs(soil_moisture=26, moisture_threshold=35, temperature=20), config=CONFIG)
    high = evaluate(_inputs(soil_moisture=10, moisture_threshold=35, temperature=20), config=CONFIG)
    assert low.urgency == Urgency.LOW
    assert medium.urgency == Urgency.MEDIUM
    assert high.urgency == Urgency.HIGH


def test_high_temperature_bumps_urgency_up_one_level():
    cool = evaluate(_inputs(soil_moisture=30, moisture_threshold=35, temperature=20), config=CONFIG)
    hot = evaluate(_inputs(soil_moisture=30, moisture_threshold=35, temperature=36), config=CONFIG)
    assert cool.urgency == Urgency.LOW
    assert hot.urgency == Urgency.MEDIUM
    assert "temperature" in hot.reason.lower()


def test_very_low_moisture_and_high_temperature_stays_high_not_overflowing():
    decision = evaluate(_inputs(soil_moisture=5, moisture_threshold=35, temperature=40), config=CONFIG)
    assert decision.urgency == Urgency.HIGH


def test_missing_weather_data_defaults_to_no_rain_and_still_decides():
    decision = evaluate(_inputs(soil_moisture=20, forecast_rainfall_mm=None, rain_probability=None), config=CONFIG)
    assert decision.recommendation == Recommendation.IRRIGATION_REQUIRED


def test_reason_is_always_a_nonempty_string():
    for sm in (5, 34.9, 35, 36, 90):
        decision = evaluate(_inputs(soil_moisture=sm), config=CONFIG)
        assert isinstance(decision.reason, str)
        assert len(decision.reason) > 15


def test_decision_preserves_zone_and_reading_id():
    decision = evaluate(_inputs(zone_id="zone-tomato", soil_moisture=10, reading_id="reading-abc123"))
    assert decision.zone_id == "zone-tomato"
    assert decision.reading_id == "reading-abc123"
