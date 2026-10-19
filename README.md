# 🌱 AgriIoT — Agricultural IoT Environmental Monitoring System

A cloud-based system that collects soil sensor data, combines it with a 7-day local weather forecast, and automatically emails alerts through Amazon SES when a field needs irrigation.

---

## What It Does

1. **IoT devices send soil readings** (moisture, temperature, humidity) to a REST API
2. The system **checks the 7-day weather forecast** from OpenWeatherMap (rain expected? hold off on irrigation)
3. A **decision engine** evaluates whether irrigation is needed
4. If irrigation is required, an **email alert is sent automatically** through Amazon SES to the farm owner and every registered subscriber
5. A **web dashboard** shows every zone, its moisture trend, the forecast, alerts, and a live log of weather API calls and email deliveries

---

## Architecture

```
IoT Sensor → API Gateway → Lambda → DynamoDB
                              │
                              ├──→ OpenWeatherMap One Call 3.0 (7-day forecast, API key)
                              └──→ Amazon SES → email to the owner and registered subscribers
```

Built on **AWS**: API Gateway, Lambda (Python 3.12), DynamoDB, SES, EventBridge (scheduled forecast refresh)
Weather data from **OpenWeatherMap** One Call API 3.0
Frontend: **React + Vite** (TypeScript), light and dark themes

---

## Project Structure

```
CAD DA3/
├── backend/
│   ├── lambda_function.py  # Single-file Lambda (paste into the AWS console)
│   └── src/
│       ├── handlers/       # Lambda functions (API entry points)
│       ├── integrations/   # Weather API clients
│       ├── services/       # Irrigation engine, weather service, API activity tracking
│       ├── models/         # Data shapes (Zone, Reading, Alert, Forecast…)
│       ├── repositories/   # DynamoDB read/write
│       └── utils/          # Config, error handling, responses
│
├── frontend/               # React dashboard (npm run dev)
│   └── src/pages/          # Dashboard, Zones, Alerts, Email alerts, Integrations
├── infrastructure/
│   └── template.yaml       # AWS SAM — deploys everything to AWS
└── docs/                   # Architecture, database schema, deployment guide
```

---

## Key Features

### Irrigation Decision Logic (no ML, fully explainable)
```
Soil moisture OK?                 → No irrigation needed
Soil moisture low + rain coming?  → Wait for rain
Soil moisture low + no rain?      → IRRIGATE (email sent automatically)
```
Rain counts as significant when at least 5 mm is forecast with at least a 50% chance within the next 2 days.
Urgency scales with how far below its threshold the moisture is.
High temperature (> 32°C) raises urgency one level.

The 25% default moisture threshold and the other limits are example values for demonstration. They are not agricultural recommendations; set real thresholds per crop and soil.

### Forecast Handling
Forecast data is never invented. If the weather API fails (invalid key, rate limit, timeout), the decision is stored with `forecast_available = false`, and its reason states that the forecast is unavailable and should be checked before irrigating. A failed request is never treated as zero rainfall.

### Automatic Email Alerts (Amazon SES)
Every reading runs through the engine. When the result is `IRRIGATION_REQUIRED`, the Lambda sends an email through Amazon SES straight away. No manual step is involved.
Alerts have a **6-hour cooldown** per zone, so a long dry spell doesn't flood inboxes.

Recipients are:
- the fixed addresses in `ALERT_EMAIL_TO` (for example the farm owner)
- everyone registered on the **Email alerts** page, for all zones or chosen ones

Registering sends a welcome email. While SES is in sandbox mode, registering also triggers an SES verification email, which the subscriber must confirm before alerts can reach them.

Each alert email contains:
- the recommendation and what to do (irrigate to target, hold for rain, or no action)
- the latest sensor reading: soil moisture vs threshold, temperature, humidity
- the upcoming forecast: conditions, high/low, rain in mm, chance of rain
- the engine's reasoning

### Manual Alert Trigger
The **Trigger alert** button on the dashboard evaluates the zone immediately and sends the emails straight away, without waiting for the cooldown.

### Live API Visibility
Every call to the weather API is recorded with its endpoint, **masked API key**, HTTP status and latency. Every SES send is recorded with its MessageId or error. The **Integrations** page shows both as they happen. Keys and email addresses are never shown in full.

### Dashboard
- Zone selector with a 7-day forecast strip and current field conditions
- 72-hour soil moisture chart with the zone's threshold marked
- Active alerts with one-click acknowledge
- Auto-refreshes every few seconds, with a pop-up whenever an alert email is sent
- Light and dark mode (follows the system setting, toggle in the top bar)

---

## Getting Started

### 1. Get a Weather API Key
Sign up at [openweathermap.org](https://openweathermap.org/api) and subscribe to **One Call by Call** (One Call API 3.0, 1,000 calls/day free). Set the daily call limit to 1,000 under *Billing plans*.

### 2. Set Up Amazon SES
1. In the AWS console, open **Amazon SES → Identities → Create identity**, choose **Email address**, enter your sender address, and click the verification link sent to it.
2. New accounts start in the **SES sandbox**, where every recipient must also be verified. Verify the owner address the same way. Subscribers who register on the dashboard receive the verification email automatically.
3. To email unverified addresses, request production access under **SES → Account dashboard**.

### 3. Configure Environment
```bash
copy .env.example .env
# Edit .env:
#   OPENWEATHER_API_KEY=your_key_here
#   SES_SENDER_EMAIL=verified-sender@example.com
#   ALERT_EMAIL_TO=owner@example.com
```

### 4. Run Backend Tests
```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest tests/unit/ -v
```

### 5. Deploy to AWS

**Option A — Lambda console (single file)**
1. Create the 7 DynamoDB tables (keys and indexes as defined in [`infrastructure/template.yaml`](infrastructure/template.yaml)).
2. Create a Lambda function (**Python 3.12**). Paste `backend/lambda_function.py` into the code editor and click **Deploy**.
   - Handler: `lambda_function.lambda_handler`
   - Timeout: 30 s
3. Add the environment variables listed below.
4. Give the function's role:
   - DynamoDB access to the 7 tables and their indexes
   - `ses:SendEmail`, `ses:SendRawEmail` and `ses:VerifyEmailIdentity`
   - basic CloudWatch logging
5. Create an API Gateway API with a `/{proxy+}` resource, method **ANY**, using Lambda proxy integration to the function, then deploy it.
6. Optional: add an EventBridge schedule, `rate(6 hours)`, targeting the function to refresh every zone's forecast.

**Option B — AWS SAM**
```bash
sam build --template infrastructure/template.yaml
sam deploy --guided
```

Either way, put the **API Gateway URL** in `frontend/.env.local` as `VITE_API_BASE_URL`.

### 6. Run the Dashboard
```bash
cd frontend
npm install
npm run dev
# → http://localhost:5173
```

---

## API Endpoints

| Method | Endpoint | What it does |
|--------|----------|-------------|
| POST | `/zones` | Create a zone |
| GET | `/zones` | List all zones |
| GET / PUT / DELETE | `/zones/{id}` | Read, update or delete a zone |
| POST | `/zones/{id}/readings` | Submit a sensor reading (runs the engine, emails if needed) |
| POST | `/api/sensor-data` | Alternative sensor format: `{farmId, soilMoisture, temperature, humidity, latitude, longitude}` |
| GET | `/zones/{id}/readings?hours=72` | Reading history for charts |
| GET | `/zones/{id}/weather` | Cached 7-day forecast |
| POST | `/zones/{id}/weather/refresh` | Fetch a fresh forecast from the weather API |
| GET | `/zones/{id}/irrigation/latest` | Latest irrigation decision |
| GET | `/irrigation/decisions` | Decision history |
| GET | `/alerts` | List alerts (`?status=active`) |
| GET / PATCH | `/alerts/{id}` | Read or acknowledge an alert |
| POST | `/zones/{id}/alerts/trigger` | Send an alert email now, bypassing the cooldown |
| POST | `/subscribers` | Register `{name, email, zone_ids?}` for email alerts |
| GET | `/subscribers` | List subscribers (emails masked) |
| DELETE | `/subscribers/{id}` | Unsubscribe |
| GET | `/system/status` | Configured integrations (secrets masked) |
| GET | `/system/activity?stream=weather\|sensor\|email` | Recent weather calls, sensor ingests and email deliveries |

Errors return clear JSON with a proper status code: 400 for invalid input, 404 for an unknown zone, 409 for duplicates, and 502 when AWS is unavailable.

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `OPENWEATHER_API_KEY` | Your OpenWeatherMap key (One Call 3.0) |
| `SES_SENDER_EMAIL` | Verified SES identity used as the From address |
| `ALERT_EMAIL_TO` | Optional comma-separated addresses that receive every alert |
| `ZONES_TABLE`, `READINGS_TABLE`, `WEATHER_CACHE_TABLE`, `ALERTS_TABLE`, `IRRIGATION_DECISIONS_TABLE`, `ACTIVITY_TABLE`, `SUBSCRIBERS_TABLE` | DynamoDB table names |
| `ALERT_COOLDOWN_MINUTES` | Minimum minutes between repeat alerts per zone (default: 360) |
| `DEFAULT_MOISTURE_THRESHOLD` | Threshold for zones created via `/api/sensor-data` (default: 25, example value) |
| `FORECAST_DAYS` | Forecast length (default: 7) |
| `FORECAST_MAX_AGE_HOURS` | How long a cached forecast is reused (default: 12) |
| `RAIN_SIGNIFICANT_MM` / `RAIN_PROBABILITY_THRESHOLD_PCT` | Rain rule (defaults: 5 mm, 50%) |
| `HIGH_TEMPERATURE_C` | Temperature that raises urgency (default: 32) |
| `CORS_ALLOWED_ORIGIN` | Allowed frontend origin (default: `*`) |

Moisture thresholds are set per zone when it is created. Full list in [`.env.example`](.env.example).

---

## Docs

- [`docs/architecture.md`](docs/architecture.md) — Data flow diagrams
- [`docs/database.md`](docs/database.md) — DynamoDB table schemas
- [`docs/deployment.md`](docs/deployment.md) — Step-by-step deployment guide
