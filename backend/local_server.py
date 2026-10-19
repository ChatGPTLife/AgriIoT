"""
Local end-to-end test server — no AWS account needed.

Runs the real Lambda handlers behind a tiny HTTP server on
http://localhost:3001, with DynamoDB and SNS replaced by moto's
in-memory mocks. Every SNS publish (topic or direct SMS) is printed to
the console so you can see exactly what would be texted.

Usage (from backend/):
    python local_server.py                      # seeded history + live sensor simulator
    python local_server.py --real-sns           # + real SMS through your AWS account
    python local_server.py --no-simulator       # seeded history, no live readings
    python local_server.py --empty              # start with no data at all
    python local_server.py --fake-weather dry   # synthetic 7-day dry forecast
    python local_server.py --fake-weather rainy # synthetic 7-day rainy forecast

--real-sns sends SNS traffic to AWS (credentials from `aws configure`) while
DynamoDB stays in memory. Set ALERT_SMS_PHONE_NUMBERS in ../.env.

Data lives in memory only. It is lost when the server stops and re-seeded
(relative to the current time) on every start.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

BACKEND_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_ROOT))


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader — real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv(BACKEND_ROOT.parent / ".env")

REAL_SNS = "--real-sns" in sys.argv
if not REAL_SNS:
    # moto needs *some* credentials; these are dummies and never leave the process.
    for _k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        os.environ[_k] = "local-testing"
os.environ.pop("DYNAMODB_ENDPOINT_URL", None)
# If the real weather call fails (e.g. One Call 3.0 not active yet), cache a
# synthetic forecast instead. The failed call is still logged.
os.environ.setdefault("WEATHER_FALLBACK", "synthetic")
# Keep the demo zone's next two days dry so it can reach IRRIGATION_REQUIRED.
os.environ.setdefault("SYNTHETIC_DRY_ZONES", "north-field")
os.environ["CORS_ALLOWED_ORIGIN"] = "*"

import boto3  # noqa: E402
from moto import mock_aws  # noqa: E402

# (method, resource template, "module:function")
ROUTES = [
    ("POST", "/zones", "zones_router:handler"),
    ("GET", "/zones", "zones_router:handler"),
    ("GET", "/zones/{zone_id}", "zones_router:handler"),
    ("PUT", "/zones/{zone_id}", "zones_router:handler"),
    ("DELETE", "/zones/{zone_id}", "zones_router:handler"),
    ("POST", "/zones/{zone_id}/readings", "readings_router:handler"),
    ("GET", "/zones/{zone_id}/readings", "readings_router:handler"),
    ("GET", "/zones/{zone_id}/weather", "weather_router:handler"),
    ("POST", "/zones/{zone_id}/weather/refresh", "weather_router:handler"),
    ("GET", "/alerts", "alerts_router:handler"),
    ("GET", "/alerts/{alert_id}", "alerts_router:handler"),
    ("PATCH", "/alerts/{alert_id}", "alerts_router:handler"),
    ("GET", "/irrigation/decisions", "irrigation_router:handler"),
    ("GET", "/zones/{zone_id}/irrigation/latest", "irrigation_router:handler"),
    ("GET", "/system/status", "system_router:handler"),
    ("POST", "/subscribers", "notifications_router:handler"),
    ("GET", "/subscribers", "notifications_router:handler"),
    ("DELETE", "/subscribers/{subscriber_id}", "notifications_router:handler"),
    ("POST", "/zones/{zone_id}/alerts/trigger", "notifications_router:handler"),
    ("GET", "/system/activity", "system_router:handler"),
]


def _compile(template: str) -> re.Pattern:
    return re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", template) + "/?$")


_COMPILED = [(m, t, _compile(t), h) for m, t, h in ROUTES]


def _resolve_handler(spec: str):
    import importlib

    module_name, func_name = spec.split(":")
    module = importlib.import_module(f"src.handlers.{module_name}")
    return getattr(module, func_name)


def create_tables() -> None:
    """Create tables/GSIs matching infrastructure/template.yaml."""
    from src.utils.config import get_config

    config = get_config()
    client = boto3.client("dynamodb", region_name=config.aws_region)
    S = lambda name: {"AttributeName": name, "AttributeType": "S"}  # noqa: E731
    key = lambda h, r=None: [{"AttributeName": h, "KeyType": "HASH"}] + (  # noqa: E731
        [{"AttributeName": r, "KeyType": "RANGE"}] if r else []
    )
    gsi = lambda name, h, r: {  # noqa: E731
        "IndexName": name, "KeySchema": key(h, r), "Projection": {"ProjectionType": "ALL"}
    }

    client.create_table(TableName=config.zones_table, AttributeDefinitions=[S("zone_id")],
                        KeySchema=key("zone_id"), BillingMode="PAY_PER_REQUEST")
    client.create_table(TableName=config.readings_table, AttributeDefinitions=[S("zone_id"), S("timestamp")],
                        KeySchema=key("zone_id", "timestamp"), BillingMode="PAY_PER_REQUEST")
    client.create_table(TableName=config.weather_cache_table, AttributeDefinitions=[S("zone_id"), S("forecast_date")],
                        KeySchema=key("zone_id", "forecast_date"), BillingMode="PAY_PER_REQUEST")
    client.create_table(
        TableName=config.alerts_table,
        AttributeDefinitions=[S("alert_id"), S("zone_id"), S("created_at"), S("status")],
        KeySchema=key("alert_id"),
        GlobalSecondaryIndexes=[gsi("ZoneIndex", "zone_id", "created_at"),
                                gsi("StatusIndex", "status", "created_at")],
        BillingMode="PAY_PER_REQUEST",
    )
    client.create_table(
        TableName=config.irrigation_decisions_table,
        AttributeDefinitions=[S("zone_id"), S("evaluated_at"), S("record_type")],
        KeySchema=key("zone_id", "evaluated_at"),
        GlobalSecondaryIndexes=[gsi("AllDecisionsByTimeIndex", "record_type", "evaluated_at")],
        BillingMode="PAY_PER_REQUEST",
    )
    client.create_table(TableName=config.subscribers_table, AttributeDefinitions=[S("subscriber_id")],
                        KeySchema=key("subscriber_id"), BillingMode="PAY_PER_REQUEST")
    client.create_table(TableName=config.activity_table, AttributeDefinitions=[S("stream"), S("created_at")],
                        KeySchema=key("stream", "created_at"), BillingMode="PAY_PER_REQUEST")


def _print_sns_publish(params, **_kwargs) -> None:
    target = params.get("PhoneNumber") or params.get("TopicArn")
    bar = "=" * 64
    print(f"\n{bar}\n  SNS PUBLISH (mocked) -> {target}")
    if params.get("Subject"):
        print(f"  Subject: {params['Subject']}")
    print(bar)
    print(params.get("Message", ""))
    print(f"{bar}\n", flush=True)


def _install_fake_weather(mode: str) -> None:
    """Replace the weather provider with a deterministic synthetic forecast."""
    from src.integrations import weather_provider
    from src.models.weather import ForecastDay
    from src.utils.ids import utc_now_iso

    rainy = mode == "rainy"

    def fake_fetch(zone_id, latitude, longitude, days=None, config=None):
        from src.utils.config import get_config

        n = days or (config or get_config()).forecast_days
        today = date.today()
        return [
            ForecastDay(
                zone_id=zone_id,
                forecast_date=(today + timedelta(days=i)).isoformat(),
                fetched_at=utc_now_iso(),
                temperature_min=22.0 if rainy else 26.0,
                temperature_max=27.0 if rainy else 35.0,
                humidity=85.0 if rainy else 35.0,
                precipitation_mm=12.0 if rainy else 0.0,
                precipitation_probability=90.0 if rainy else 5.0,
                condition="rain" if rainy else "clear",
                provider=f"fake-{mode}",
            )
            for i in range(n)
        ]

    weather_provider.get_provider = lambda config=None: fake_fetch
    # weather_service imported the name directly, so patch it there too.
    from src.services import weather_service

    weather_service.get_provider = weather_provider.get_provider


class Handler(BaseHTTPRequestHandler):
    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type,Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,PATCH,DELETE,OPTIONS")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _dispatch(self) -> None:
        url = urlsplit(self.path)
        method = self.command.upper()
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8") if length else None

        for route_method, template, pattern, spec in _COMPILED:
            match = pattern.match(url.path)
            if match and route_method == method:
                event = {
                    "httpMethod": method,
                    "resource": template,
                    "path": url.path,
                    "pathParameters": match.groupdict() or None,
                    "queryStringParameters": dict(parse_qsl(url.query)) or None,
                    "headers": dict(self.headers),
                    "body": body,
                    "isBase64Encoded": False,
                }
                result = _resolve_handler(spec)(event, None)
                self._send(result.get("statusCode", 200), result.get("body") or "")
                return
        self._send(404, json.dumps({"error": f"No route for {method} {url.path}"}))

    def _send(self, status: int, body: str) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self._cors()
        self.end_headers()
        self.wfile.write(payload)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _dispatch  # noqa: N815


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=3001)
    parser.add_argument("--fake-weather", choices=["dry", "rainy"],
                        help="use a synthetic forecast instead of calling the weather API")
    parser.add_argument("--empty", action="store_true",
                        help="don't seed history or start the sensor simulator")
    parser.add_argument("--no-simulator", action="store_true",
                        help="seed history but don't stream live readings")
    parser.add_argument("--demo", action="store_true", help=argparse.SUPPRESS)  # old flag; now the default
    parser.add_argument("--real-sns", action="store_true",
                        help="send SMS through real AWS SNS (DynamoDB stays in memory)")
    parser.add_argument("--interval", type=float, default=15, help="simulator seconds between readings")
    args = parser.parse_args()

    import logging

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.real_sns and not os.environ.get("ALERT_SMS_PHONE_NUMBERS") and not os.environ.get("SNS_TOPIC_ARN"):
        sys.exit("--real-sns needs ALERT_SMS_PHONE_NUMBERS (e.g. +919876543210) or SNS_TOPIC_ARN in ../.env")

    mock_config = {"core": {"mock_credentials": False, "passthrough": {"services": ["sns"]}}} if args.real_sns else None
    with mock_aws(config=mock_config):
        from src.utils.config import get_config, reset_config_cache

        boto3.setup_default_session()
        boto3.DEFAULT_SESSION.events.register("provide-client-params.sns.Publish", _print_sns_publish)

        if args.real_sns:
            os.environ["SNS_MODE"] = "aws"
        else:
            os.environ["SNS_MODE"] = "mock"
            region = os.environ.get("AWS_REGION", "us-east-1")
            topic_arn = boto3.client("sns", region_name=region).create_topic(Name="AgriIot-Alerts-local")["TopicArn"]
            os.environ["SNS_TOPIC_ARN"] = topic_arn
        reset_config_cache()
        create_tables()

        if args.fake_weather:
            _install_fake_weather(args.fake_weather)

        if not args.empty:
            from demo_seed import seed

            print(f"Seeded demo data: {seed()}")

        config = get_config()
        weather = f"fake ({args.fake_weather})" if args.fake_weather else config.weather_provider
        sns = "REAL AWS SNS" if args.real_sns else "in-memory mock"
        from src.utils.config import email_mode

        email = "Gmail SMTP (real)" if email_mode(config) == "smtp" else "simulated (set SMTP_USER + SMTP_APP_PASSWORD)"
        print(f"\nLocal API on http://localhost:{args.port}  |  weather: {weather}  |  "
              f"DynamoDB: in-memory mock  |  SNS: {sns}  |  email: {email}\n", flush=True)
        # No SO_REUSEADDR: on Windows it lets a second server silently share the port.
        HTTPServer.allow_reuse_address = False
        # Single-threaded keeps moto's in-memory state simple; a deep backlog lets
        # the dashboard's parallel requests queue instead of being refused.
        HTTPServer.request_queue_size = 128
        try:
            server = HTTPServer(("127.0.0.1", args.port), Handler)
        except OSError:
            sys.exit(f"\nPort {args.port} is already in use — another local_server.py is probably still running.\n"
                     f"Stop it (Ctrl+C in its terminal, or Task Manager → python.exe), or use --port {args.port + 1}.")

        stop = threading.Event()
        if not args.empty and not args.no_simulator:
            from sensor_simulator import run as run_simulator

            threading.Thread(
                target=run_simulator, daemon=True,
                args=(f"http://127.0.0.1:{args.port}", args.interval, "north-field", 0.9, 30, stop),
            ).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            stop.set()
            print("\nStopped.")


if __name__ == "__main__":
    main()
