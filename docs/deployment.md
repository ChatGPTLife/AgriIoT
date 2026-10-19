# Deployment Guide

## Prerequisites

| Tool | Minimum version |
|---|---|
| AWS CLI | 2.x |
| AWS SAM CLI | 1.100+ |
| Python | 3.12 |
| Node.js | 20 LTS (for frontend) |

---

## 1. AWS Setup

### 1.1 Configure credentials
```bash
aws configure
# Enter: Access Key ID, Secret Access Key, region (e.g. us-east-1), output format (json)
```

### 1.2 Create SSM parameters for secrets
```bash
# OpenWeatherMap API key
aws ssm put-parameter \
  --name /agriiot/openweather_api_key \
  --value "YOUR_KEY_HERE" \
  --type SecureString

# Tomorrow.io API key (only needed if switching provider)
aws ssm put-parameter \
  --name /agriiot/tomorrowio_api_key \
  --value "YOUR_KEY_HERE" \
  --type SecureString
```

---

## 2. Deploy the Backend (AWS SAM)

```bash
cd "c:\Reverse\CAD DA3"

# Build Lambda packages
sam build --template infrastructure/template.yaml

# First deploy — interactive wizard, saves samconfig.toml
sam deploy --guided

# Subsequent deploys
sam deploy
```

### Key SAM parameters prompted during `--guided`:
| Parameter | Recommended value |
|---|---|
| `AppEnv` | `prod` |
| `WeatherProvider` | `openweather` (or `tomorrowio`) |
| `AlertSmsPhoneNumbers` | `+15551234567` (E.164 format, comma-separated) |
| `CorsAllowedOrigin` | `https://your-frontend-domain.com` |

After deploy, SAM outputs the **ApiBaseUrl**. Copy it.

---

## 3. Deploy the Frontend

```bash
cd "c:\Reverse\CAD DA3\frontend"
npm install

# Create .env for production
echo "VITE_API_BASE_URL=https://<api-id>.execute-api.<region>.amazonaws.com/prod" > .env.production

npm run build
# Output: frontend/dist/
```

Deploy `frontend/dist/` to:
- **AWS S3 + CloudFront** (recommended)
- Vercel / Netlify (free tier available)
- Any static hosting

---

## 4. Local Development

### 4.1 Backend — Local DynamoDB

```bash
# Install DynamoDB Local (Docker)
docker run -p 8000:8000 amazon/dynamodb-local

# Copy and configure .env
copy .env.example .env
# Set DYNAMODB_ENDPOINT_URL=http://localhost:8000

# Install Python deps
pip install -r backend/requirements.txt -r backend/requirements-dev.txt

# Run unit tests
cd backend
pytest
```

### 4.2 Simulating the ingest pipeline locally

```python
# Set env vars then run Python REPL:
import os, json
os.environ["DYNAMODB_ENDPOINT_URL"] = "http://localhost:8000"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"

from src.services.irrigation_engine import IrrigationInputs, evaluate
result = evaluate(IrrigationInputs(
    zone_id="test-zone",
    soil_moisture=25.0,
    moisture_threshold=40.0,
    target_moisture=60.0,
    temperature=35.0,
    forecast_rainfall_mm=2.0,
    rain_probability=30.0,
))
print(result.model_dump_json(indent=2))
```

### 4.3 Frontend local dev

```bash
cd "c:\Reverse\CAD DA3\frontend"
npm install

# Create local .env
echo "VITE_API_BASE_URL=http://localhost:3001" > .env

npm run dev
# Opens http://localhost:5173
```

---

## 5. Teardown

```bash
sam delete --stack-name agri-iot-prod
```

> [!CAUTION]
> DynamoDB tables have `DeletionPolicy: Retain`. Delete them manually in
> the console if you want a full teardown.

---

## 6. Adding an SMS Subscriber via Console

1. Open **SNS → Topics → AgriIot-Alerts-prod**
2. Click **Create subscription**
3. Protocol: `SMS`, Endpoint: phone number in E.164 format
4. Confirm subscription (AWS sends a test SMS)

---

## 7. Switching Weather Provider

```bash
sam deploy --parameter-overrides WeatherProvider=tomorrowio
```

No code changes needed. The factory in `src/integrations/weather_provider.py`
selects the correct HTTP client automatically.
