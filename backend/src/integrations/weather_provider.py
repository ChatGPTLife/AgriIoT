"""
Weather provider factory.

Returns the correct provider's `fetch_forecast` callable based on the
WEATHER_PROVIDER environment variable ("openweather", "tomorrowio" or
"synthetic"). The caller receives a single unified function signature:

    fetch_forecast(zone_id, latitude, longitude, days?, config?) -> List[ForecastDay]

With WEATHER_FALLBACK=synthetic, a failed provider call (bad key,
timeout, rate limit…) falls back to the synthetic provider. The failed
call is still recorded in the API activity log.

Adding a third provider in the future requires only:
  1. A new module in src/integrations/
  2. A new entry in _PROVIDERS below
"""
from __future__ import annotations

import logging
from typing import Callable, List

from src.integrations import openweather, synthetic, tomorrowio
from src.models.weather import ForecastDay
from src.utils.config import AppConfig, get_config
from src.utils.errors import AppError, ConfigurationError

logger = logging.getLogger(__name__)

# Registry: provider name → module with a fetch_forecast function
_PROVIDERS = {
    "openweather": openweather,
    "tomorrowio": tomorrowio,
    "synthetic": synthetic,
}


def get_provider(config: AppConfig | None = None) -> Callable[..., List[ForecastDay]]:
    """
    Return the `fetch_forecast` callable for the configured weather provider.

    Raises ConfigurationError if the WEATHER_PROVIDER value is not recognised.
    """
    config = config or get_config()
    provider_name = config.weather_provider.lower()

    module = _PROVIDERS.get(provider_name)
    if module is None:
        raise ConfigurationError(
            f"Unknown WEATHER_PROVIDER '{provider_name}'. "
            f"Must be one of: {', '.join(_PROVIDERS)}."
        )

    fetch = module.fetch_forecast  # type: ignore[attr-defined]
    if config.weather_fallback != "synthetic" or module is synthetic:
        return fetch

    def fetch_with_fallback(zone_id, latitude, longitude, days=None, config=None):
        try:
            return fetch(zone_id=zone_id, latitude=latitude, longitude=longitude, days=days, config=config)
        except AppError as exc:
            logger.warning("%s failed for zone=%s (%s) — using synthetic forecast", provider_name, zone_id, exc.message)
            return synthetic.fetch_forecast(zone_id, latitude, longitude, days=days, config=config)

    return fetch_with_fallback
