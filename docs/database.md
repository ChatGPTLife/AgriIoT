# Database — DynamoDB Schema & Access Patterns

## Tables Overview

| Table | PK | SK | Purpose |
|---|---|---|---|
| `AgriIot-Zones` | `zone_id` | — | One row per agricultural zone |
| `AgriIot-SensorReadings` | `zone_id` | `timestamp` | Time-series sensor data |
| `AgriIot-WeatherForecastCache` | `zone_id` | `forecast_date` | Cached 7-day forecasts |
| `AgriIot-Alerts` | `alert_id` | — | Irrigation alerts with status |
| `AgriIot-IrrigationDecisions` | `zone_id` | `evaluated_at` | Full decision history |

---

## Zones Table

**PK:** `zone_id` (String, slug e.g. `"north-field"`)

| Attribute | Type | Notes |
|---|---|---|
| zone_id | S | Auto-generated from name via slugify() if not provided |
| name | S | Human-readable zone name |
| latitude | N | WGS-84 |
| longitude | N | WGS-84 |
| crop_type | S | e.g. "wheat", "tomato" |
| soil_type | S | e.g. "loamy", "sandy" |
| moisture_threshold | N | % below which irrigation is considered |
| target_moisture | N | % irrigation aims to restore (must > threshold) |
| enabled | BOOL | Disabled zones reject sensor readings |
| created_at | S | ISO 8601 UTC |
| updated_at | S | ISO 8601 UTC |

**Access patterns:**
- `GET /zones` → `Scan` (acceptable at farm-scale, typically < 100 zones)
- `GET /zones/{zone_id}` → `GetItem`
- `POST/PUT/DELETE` → `PutItem` / `UpdateItem` / `DeleteItem` with conditional check

---

## SensorReadings Table

**PK:** `zone_id` **SK:** `timestamp` (ISO 8601 UTC)

| Attribute | Type | Notes |
|---|---|---|
| reading_id | S | Unique identifier (rdg-xxxxxxxx) |
| zone_id | S | |
| timestamp | S | ISO 8601 UTC — used as SK for range queries |
| soil_moisture | N | Volumetric %, 0–100 |
| temperature | N | Celsius, –40 to +70 |
| humidity | N | Relative %, 0–100 |
| device_id | S | Optional sensor device identifier |
| created_at | S | ISO 8601 UTC |
| ttl | N | (Optional) Unix epoch for DynamoDB TTL — set to auto-expire old readings |

**Access patterns:**
- `POST /zones/{zone_id}/readings` → `PutItem`
- Latest reading per zone → `Query` PK=zone_id, ScanIndexForward=False, Limit=1
- Historical range → `Query` with SK `between(start, end)`

---

## WeatherForecastCache Table

**PK:** `zone_id` **SK:** `forecast_date` (YYYY-MM-DD)

| Attribute | Type | Notes |
|---|---|---|
| zone_id | S | |
| forecast_date | S | YYYY-MM-DD UTC |
| fetched_at | S | ISO 8601 — when this row was last written |
| temperature_min | N | Celsius |
| temperature_max | N | Celsius |
| humidity | N | % |
| precipitation_mm | N | Expected rainfall mm for this day |
| precipitation_probability | N | 0–100% |
| condition | S | e.g. "rain", "clear", "cloudy" |
| provider | S | "openweather" or "tomorrowio" |

**Access patterns:**
- Read 7 days for a zone → `Query` PK=zone_id, ScanIndexForward=True, Limit=7
- Forecast summary for engine → aggregate precipitation across window
- Refresh → `BatchWriteItem` (overwrite_by_pkeys)

---

## Alerts Table

**PK:** `alert_id`  
**GSI 1 — ZoneIndex:** PK=`zone_id` SK=`created_at`  
**GSI 2 — StatusIndex:** PK=`status` SK=`created_at`

| Attribute | Type | Notes |
|---|---|---|
| alert_id | S | alert-xxxxxxxxxxxx |
| zone_id | S | |
| zone_name | S | Denormalised for display without a join |
| created_at | S | ISO 8601 UTC |
| status | S | "active" or "acknowledged" |
| urgency | S | NONE / LOW / MEDIUM / HIGH |
| reason | S | Human-readable explanation |
| soil_moisture | N | At time of alert |
| threshold | N | Zone's moisture_threshold at time of alert |
| expected_rainfall_mm | N | From forecast |
| rain_probability | N | From forecast |
| acknowledged_at | S | ISO 8601 UTC, set on acknowledge |

**Access patterns:**
- `GET /alerts` (all) → `Scan` (acceptable at alert volume)
- `GET /alerts?status=active` → `Query` StatusIndex PK=active
- `GET /alerts?zone_id=X` → `Query` ZoneIndex PK=zone_id
- Cooldown check → `Query` ZoneIndex PK=zone_id, ScanIndexForward=False, Limit=1
- `GetItem` by alert_id → primary key lookup
- Acknowledge → `UpdateItem` with conditional check

---

## IrrigationDecisions Table

**PK:** `zone_id` **SK:** `evaluated_at` (ISO 8601 UTC)  
**GSI — AllDecisionsByTimeIndex:** PK=`record_type` (constant "DECISION") SK=`evaluated_at`

| Attribute | Type | Notes |
|---|---|---|
| zone_id | S | |
| evaluated_at | S | ISO 8601 UTC |
| record_type | S | Always "DECISION" — enables cross-zone GSI |
| recommendation | S | NO_IRRIGATION_NEEDED / WAIT_FOR_RAIN / IRRIGATION_REQUIRED |
| urgency | S | NONE / LOW / MEDIUM / HIGH |
| reason | S | Human-readable explanation |
| soil_moisture | N | |
| moisture_threshold | N | |
| target_moisture | N | |
| temperature | N | Optional |
| humidity | N | Optional |
| forecast_rainfall_mm | N | Optional |
| rain_probability | N | Optional |
| reading_id | S | Optional — links to SensorReadings |

**Access patterns:**
- Latest decision for a zone → `Query` PK=zone_id, ScanIndexForward=False, Limit=1
- Decision history for a zone → `Query` PK=zone_id
- All decisions across zones → `Query` AllDecisionsByTimeIndex PK=DECISION

---

## Scaling Notes

The current `Scan` on Zones and the StatusIndex `Scan` fallback in Alerts
are acceptable at farm scale (< 500 zones, < 10 k alerts). For larger
deployments, consider:

- Replacing the Zones scan with a fan-out GSI (PK=`record_type`, SK=`zone_id`)
- Partitioning alerts by month in the StatusIndex SK (`YYYY-MM#created_at`)
- Adding DynamoDB Streams + Lambda to maintain pre-aggregated summaries
