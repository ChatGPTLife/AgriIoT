# Live demo runbook

What the audience sees:

1. **Dashboard** — four zones with 7 days of sensor history, a 7-day forecast strip, and a
   chip showing the live OpenWeatherMap call (masked API key, HTTP status, latency).
2. **North Field dries out on its own.** The sensor simulator posts a reading for each zone
   every few seconds through `POST /zones/{id}/readings`. North Field loses ~1% per reading.
3. About a minute later it drops below its 30% threshold. The irrigation engine returns
   `IRRIGATION_REQUIRED`, an SMS is published to Amazon SNS automatically, and a toast pops up.
4. **Integrations page** — every outbound weather API call and every SMS, as it happens, plus a
   phone-style SMS outbox.
5. A few readings later the simulator "opens the valve" and moisture recovers.

## One-time setup

### 1. Weather: activate One Call 3.0

OpenWeatherMap → *Billing plans* → subscribe to **One Call by Call** (1,000 calls/day free,
card required). Set the daily call limit to **1000** so you're never charged. Activation can take
a little while. Until then the dashboard shows `HTTP 401` honestly and decisions assume no rain.

The demo uses ~4 calls at start-up plus 4 every 30 minutes.

### 2. SMS: AWS account + SNS sandbox

```powershell
winget install Amazon.AWSCLI
aws configure            # access key, secret, region (e.g. ap-south-1)
```

AWS console → **Amazon SNS → Text messaging (SMS) → Sandbox destination phone numbers →
Add phone number** → enter the OTP you receive. New accounts can only text verified numbers.

Then in `.env` (project root):

```
AWS_REGION=ap-south-1
ALERT_SMS_PHONE_NUMBERS=+91XXXXXXXXXX
```

> **Indian numbers:** carriers in India require DLT registration for application-to-person SMS.
> Without it, SNS may accept the message (you'll see a MessageId) but the carrier can drop it.
> Test a day before. If it doesn't arrive, the on-screen SMS outbox still shows each publish
> with its real SNS MessageId. You can also add an **email** subscription to the topic as a backup.

### 3. Email: Gmail sender

1. Use (or create) a Gmail account to send from. Turn on **2-Step Verification**.
2. Google Account → Security → **App passwords** → create one for "Mail". You get a 16-character code.
3. In `.env`:
   ```
   SMTP_USER=yoursender@gmail.com
   SMTP_APP_PASSWORD=abcd efgh ijkl mnop
   ```
4. Restart the backend. The startup line should say `email: Gmail SMTP (real)`.

Recipients register on the **Email alerts** page. Subscribers live in memory locally, so
**register again after every backend restart**, before the demo starts.

## On demo day

```powershell
# terminal 1 — backend with history, live simulator, and real SMS
cd backend
python local_server.py --real-sns

# terminal 2 — dashboard
cd frontend
npm run dev
```

Open http://localhost:5173. Good order: **Email alerts → register your Gmail → Dashboard → wait for the automatic alert toast → press *Trigger alert* on another zone → show the email on your phone → Integrations**.

| Flag | Effect |
|---|---|
| *(default)* | seed 7 days of history and start the sensor simulator |
| `--no-simulator` / `--empty` | history without live readings / no data at all |
| `--real-sns` | real SMS via your AWS account (DynamoDB stays in memory) |
| `--interval 10` | seconds between simulated readings (default 15) |
| `--fake-weather dry` | synthetic forecast, if the weather API is unavailable |

Without `--real-sns` everything still works, and the SMS outbox labels each message *simulated*.

**Repeat the alert:** each zone has a 6-hour alert cooldown, so North Field sends one SMS per
run. Restart the server (Ctrl+C, run again) to reset the data and demo it again.

## Against the deployed AWS stack

After `sam deploy`, point the simulator at API Gateway instead:

```powershell
python backend/demo_seed.py   # seeds the real DynamoDB tables named in .env
python backend/sensor_simulator.py --api https://<api-id>.execute-api.<region>.amazonaws.com/prod
```
