# Architecture — Agricultural IoT Environmental Monitoring System

## Overview

```
IoT Device / Manual Sensor
         │
         ▼ POST /zones/{zone_id}/readings
   ┌─────────────────┐
   │   API Gateway   │  (REST, Lambda proxy)
   └────────┬────────┘
            │
            ▼
   ┌─────────────────────────────────────────────────────────────────┐
   │                     AWS Lambda Functions                        │
   │                                                                 │
   │  SensorIngestFunction          ZonesFunction                   │
   │  WeatherFunction               AlertsFunction                  │
   │  IrrigationFunction            WeatherRefreshFunction (cron)   │
   └──────────────────────────────────────────────────────┬──────────┘
                                                          │
            ┌─────────────────────────────────────────────┤
            │                                             │
            ▼                                             ▼
   ┌────────────────┐                          ┌─────────────────────┐
   │   DynamoDB     │                          │   Amazon SNS        │
   │                │                          │                     │
   │ Zones          │                          │  AlertsTopic        │
   │ SensorReadings │                          │  → SMS subscribers  │
   │ WeatherCache   │                          │  → Email (optional) │
   │ Alerts         │                          └─────────────────────┘
   │ IrrigDecisions │
   └────────────────┘
            │ (weather refresh)
            ▼
   ┌────────────────────────────┐
   │   External Weather APIs    │
   │  OpenWeatherMap One Call   │
   │  Tomorrow.io Timelines     │
   └────────────────────────────┘
```

## Data Flow — Sensor Reading Ingest

```
1. Device POSTs { soil_moisture, temperature, humidity } to
   POST /zones/{zone_id}/readings

2. SensorIngestFunction:
   a. Validates payload (Pydantic)
   b. Verifies zone exists + is enabled (DynamoDB Zones table)
   c. Persists reading → SensorReadings table
   d. Reads cached 2-day forecast summary from WeatherForecastCache
   e. Runs irrigation_engine.evaluate() — pure Python, no I/O
   f. Persists irrigation decision → IrrigationDecisions table

3. If recommendation == IRRIGATION_REQUIRED and alert cooldown elapsed:
   a. Publishes message to SNS AlertsTopic
   b. Optionally publishes direct SMS to ALERT_SMS_PHONE_NUMBERS
   c. Persists Alert record → Alerts table

4. Returns decision (+ IDs) to caller
```

## Data Flow — Weather Refresh

```
EventBridge Schedule (every 6 hours)
   │
   ▼
WeatherRefreshFunction
   │ for each enabled zone:
   ▼
weather_service.refresh_forecast()
   ├── GET lat/lon from Zones table
   ├── Call OpenWeatherMap / Tomorrow.io API (7-day daily forecast)
   ├── Validate ≥ 7 days returned
   └── Upsert 7 rows → WeatherForecastCache table
```

## Weather Provider Switchover

Set `WEATHER_PROVIDER=tomorrowio` (and `TOMORROWIO_API_KEY`) to switch
from OpenWeatherMap to Tomorrow.io. The rest of the system is unaffected —
both providers produce the same `ForecastDay` shape.

The factory pattern lives in `src/integrations/weather_provider.py`.

## Irrigation Decision Engine

`src/services/irrigation_engine.py` — deterministic, no ML.

```
soil_moisture >= moisture_threshold     → NO_IRRIGATION_NEEDED
soil_moisture <  moisture_threshold
  AND significant rain expected         → WAIT_FOR_RAIN
soil_moisture <  moisture_threshold
  AND no significant rain               → IRRIGATION_REQUIRED

"Significant rain" = forecast_rainfall_mm >= RAIN_SIGNIFICANT_MM
                     AND rain_probability  >= RAIN_PROBABILITY_THRESHOLD_PCT

Urgency bands (IRRIGATION_REQUIRED only):
  deficit >= 15%  → HIGH
  deficit >= 7%   → MEDIUM
  deficit <  7%   → LOW
  temperature >= HIGH_TEMPERATURE_C bumps urgency one level
```

## Alert Deduplication

A new alert is created only when `alert_cooldown_minutes` (default 6 h)
have elapsed since the last alert for the same zone. This prevents SMS
storms during a prolonged dry spell.

## Security Notes

- No secrets are hard-coded. API keys, phone numbers, and ARNs are
  injected via Lambda environment variables sourced from AWS SSM.
- The `@handle_errors` decorator ensures stack traces and AWS error
  messages never reach API clients.
- CORS `Access-Control-Allow-Origin` defaults to `*` locally but should
  be set to the exact frontend origin in production.
