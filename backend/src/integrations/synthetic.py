"""
Synthetic forecast provider.

Generates a plausible daily forecast with no external call. It is
deterministic per (zone, date), so refreshing during the same day gives
the same numbers. Used as WEATHER_PROVIDER=synthetic, or automatically
when WEATHER_FALLBACK=synthetic and the real provider call fails.

Rows are tagged provider="synthetic" so they can always be told apart
from real provider data.
"""
from __future__ import annotations

import os
import random
from datetime import date, timedelta
from typing import List

from src.models.weather import ForecastDay
from src.utils.config import AppConfig, get_config
from src.utils.ids import utc_now_iso

# (condition, rain probability range %, rain mm range, max-temp shift °C)
_PATTERNS = [
    ("clear", (0, 10), (0.0, 0.0), 1.5),
    ("partly_cloudy", (5, 25), (0.0, 0.4), 0.5),
    ("cloudy", (20, 45), (0.0, 1.5), -1.0),
    ("light_rain", (45, 70), (1.0, 6.0), -2.5),
    ("rain", (65, 90), (5.0, 16.0), -4.0),
    ("thunderstorm", (70, 95), (8.0, 25.0), -3.0),
]
_WEIGHTS = [30, 26, 18, 12, 9, 5]


def fetch_forecast(
    zone_id: str,
    latitude: float,
    longitude: float,
    days: int | None = None,
    config: AppConfig | None = None,
) -> List[ForecastDay]:
    config = config or get_config()
    n = days or config.forecast_days
    today = date.today()
    fetched_at = utc_now_iso()
    # Warmer inland/south, a little cooler with latitude.
    base_max = 33.5 - (latitude - 18.5) * 0.6

    # Zones listed in SYNTHETIC_DRY_ZONES get no significant rain in the first two
    # days, so a drying field still produces IRRIGATION_REQUIRED rather than WAIT_FOR_RAIN.
    dry = zone_id in {z.strip() for z in os.environ.get("SYNTHETIC_DRY_ZONES", "").split(",") if z.strip()}

    out: List[ForecastDay] = []
    for i in range(n):
        day = today + timedelta(days=i)
        rng = random.Random(f"{zone_id}:{day.isoformat()}")
        patterns, weights = (_PATTERNS[:3], _WEIGHTS[:3]) if dry and i < 2 else (_PATTERNS, _WEIGHTS)
        condition, prob, rain, shift = rng.choices(patterns, weights=weights)[0]
        t_max = base_max + shift + rng.uniform(-1.2, 1.2)
        out.append(
            ForecastDay(
                zone_id=zone_id,
                forecast_date=day.isoformat(),
                fetched_at=fetched_at,
                temperature_min=round(t_max - rng.uniform(8.5, 11.5), 1),
                temperature_max=round(t_max, 1),
                humidity=round(min(95, 48 + prob[1] * 0.4 + rng.uniform(-6, 6))),
                precipitation_mm=round(rng.uniform(*rain), 1),
                precipitation_probability=round(rng.uniform(*prob)),
                condition=condition,
                provider="synthetic",
            )
        )
    return out
