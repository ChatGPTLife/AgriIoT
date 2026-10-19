# 🌱 AgriIoT — Agricultural IoT Environmental Monitoring System

A cloud-based system that collects soil sensor data, combines it with a 7-day local weather forecast, and automatically sends SMS alerts when a field needs irrigation.

---

## What It Does

1. **IoT devices send soil readings** (moisture, temperature, humidity) to a REST API
2. The system **checks the 7-day weather forecast** from OpenWeatherMap (rain expected? hold off on irrigation)
3. A **decision engine** evaluates whether irrigation is needed
4. If irrigation is required, an **SMS alert is sent automatically** via Amazon SNS, and an **email alert** goes to every registered subscriber
5. A **web dashboard** shows every zone, its moisture trend, the forecast, alerts, and a live log of external API calls and SMS deliveries

---

## Architecture

```
IoT Sensor → API Gateway → Lambda → DynamoDB
                              │
                              ├──→ OpenWeatherMap One Call 3.0 (7-day forecast, API key)
                              ├──→ Amazon SNS → SMS to farmer
                              └──→ Gmail SMTP → email to registered subscribers
```

Built on **AWS**: API Gateway, Lambda (Python 3.12), DynamoDB, SNS, EventBridge (scheduled forecast refresh)
Weather data from **OpenWeatherMap** or **Tomorrow.io** (switchable with one setting)
Frontend: **React + Vite** (TypeScript), light and dark themes

---

## Project Structure

```
CAD DA3/
├── backend/
│   └── src/
│       ├── handlers/       # Lambda functions (API entry points)
│       ├── integrations/   # Weather API clients (OpenWeatherMap, Tomorrow.io)
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
Soil moisture low + no rain?      → IRRIGATE (SMS sent automatically)
```
Urgency scales with how far below its threshold the moisture is.
High temperature (> 32°C) raises urgency one level.

### Automatic SMS Alerts
Every reading runs through the engine. When the result is `IRRIGATION_REQUIRED`, the Lambda publishes to Amazon SNS straight away. No manual step is involved.
Alerts have a **6-hour cooldown** per zone, so a long dry spell doesn't send an SMS storm.

### Email Alerts
Anyone can register a Gmail address on the **Email alerts** page, for all zones or chosen ones. They get a welcome email, then an email with every alert. Each alert email contains:
- the recommendation and what to do (irrigate to target, hold for rain, or no action)
- the latest sensor reading: soil moisture vs threshold, temperature, humidity
- a 5-day weather table: conditions, high/low, rain in mm, chance of rain
- the engine's reasoning

### Manual Alert Trigger
The **Trigger alert** button on the dashboard (and in each zone's detail panel) evaluates the zone immediately and sends the SMS and emails straight away, without waiting for the cooldown.

### Live API Visibility
Every call to the weather API is recorded with its endpoint, **masked API key**, HTTP status and latency. Every SNS publish is recorded with its MessageId. The **Integrations** page shows both as they happen, along with an SMS outbox. Keys and phone numbers are never stored in full.

### Dashboard
- Zone selector with a 7-day forecast strip and current field conditions
- 72-hour soil moisture chart with the zone's threshold marked
- Active alerts with one-click acknowledge
- Auto-refreshes every few seconds, with a pop-up whenever an SMS is sent
- Light and dark mode (follows the system setting, toggle in the top bar)

---

## Getting Started

### 1. Get a Weather API Key
Sign up at [openweathermap.org](https://openweathermap.org/api) and subscribe to **One Call by Call** (One Call API 3.0, 1,000 calls/day free). Set the daily call limit to 1,000 under *Billing plans*.

### 2. Configure Environment
```bash
copy .env.example .env
# Edit .env:
#   OPENWEATHER_API_KEY=your_key_here
#   ALERT_SMS_PHONE_NUMBERS=+91XXXXXXXXXX
```

### 3. Enable SMS in Amazon SNS
New AWS accounts start in the SNS SMS sandbox. In the AWS console: **SNS → Text messaging (SMS) → Sandbox destination phone numbers → Add phone number**, then enter the code you receive.

### 4. Enable Email Alerts (Gmail)
Use a Gmail account as the sender. Turn on 2-Step Verification, then create an **App Password** (Google Account → Security → App passwords). Add to `.env`:
```
SMTP_USER=yourname@gmail.com
SMTP_APP_PASSWORD=abcd efgh ijkl mnop
```
When deploying, pass the same values as the `SmtpUser` / `SmtpAppPassword` SAM parameters.

### 5. Run Backend Tests
```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest tests/unit/ -v
# → 25 passed
```

### 6. Deploy to AWS
```bash
sam build --template infrastructure/template.yaml
sam deploy --guided
```
After deploying, SAM prints your **API Gateway URL**. Put it in `frontend/.env.local` as `VITE_API_BASE_URL`.

### 7. Run the Dashboard
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
| POST | `/zones/{id}/readings` | Submit a sensor reading (runs the engine, sends an SMS if needed) |
| GET | `/zones/{id}/readings?hours=72` | Reading history for charts |
| GET | `/zones/{id}/weather` | Cached 7-day forecast |
| POST | `/zones/{id}/weather/refresh` | Fetch a fresh forecast from the weather API |
| GET | `/zones/{id}/irrigation/latest` | Latest irrigation decision |
| GET | `/irrigation/decisions` | Decision history |
| GET | `/alerts` | List alerts (`?status=active`) |
| PATCH | `/alerts/{id}` | Acknowledge an alert |
| POST | `/zones/{id}/alerts/trigger` | Send an alert now (SMS + email), bypassing the cooldown |
| POST | `/subscribers` | Register `{name, email, zone_ids?}` for email alerts |
| GET | `/subscribers` | List subscribers (emails masked) |
| DELETE | `/subscribers/{id}` | Unsubscribe |
| GET | `/system/status` | Configured integrations (secrets masked) |
| GET | `/system/activity?stream=weather\|sensor\|sms\|email` | Recent weather calls, sensor ingests, SMS and email deliveries |

The forecast for every zone is also refreshed automatically every 6 hours by a scheduled Lambda.

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `OPENWEATHER_API_KEY` | Your OpenWeatherMap key |
| `WEATHER_PROVIDER` | `openweather` or `tomorrowio` |
| `SNS_TOPIC_ARN` | ARN of the SNS alert topic (set by SAM) |
| `ALERT_SMS_PHONE_NUMBERS` | E.164 phone numbers for SMS (e.g. `+919876543210`) |
| `SMTP_USER` / `SMTP_APP_PASSWORD` | Gmail sender and App Password for email alerts |
| `ALERT_COOLDOWN_MINUTES` | Minimum minutes between repeat alerts per zone (default: 360) |
| `FORECAST_DAYS` | Forecast length (default: 7) |

Moisture thresholds are set per zone when it is created. Full list in [`.env.example`](.env.example).

---

## Docs

- [`docs/architecture.md`](docs/architecture.md) — Data flow diagrams
- [`docs/database.md`](docs/database.md) — DynamoDB table schemas
- [`docs/deployment.md`](docs/deployment.md) — Step-by-step deployment guide
