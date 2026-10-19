"""
Field sensor simulator.

Posts a soil reading for every enabled zone through the public REST API
every few seconds, exactly as a field device would. Readings follow a
day/night temperature cycle and slow soil drying.

For the live demo, the --demo-zone dries out quickly. Once it falls below
its threshold the backend decides IRRIGATION_REQUIRED and sends the SMS
on its own. A few ticks later the simulator "opens the valve" and moisture
recovers to the target. The other zones are kept healthy.

It also refreshes the weather forecast for every zone on start-up and then
every --weather-minutes (real API calls when a key is configured).

Usage:
    python sensor_simulator.py                                   # local server
    python sensor_simulator.py --api https://<id>.execute-api.<region>.amazonaws.com/prod
"""
from __future__ import annotations

import argparse
import json
import random
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from demo_seed import DEMO_ZONE_ID, ZONES, climate

_DEVICE_IDS = {spec["zone"]["zone_id"]: spec["device_id"] for spec in ZONES}
_TEMP_OFFSETS = {spec["zone"]["zone_id"]: spec["temp_offset"] for spec in ZONES}


def _call(api: str, method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(api.rstrip("/") + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read() or b"{}")


def refresh_weather(api: str, zones) -> None:
    for zone in zones:
        result = _call(api, "POST", f"/zones/{zone['zone_id']}/weather/refresh")
        if result.get("success"):
            print(f"[weather] {zone['zone_id']}: {result.get('refreshed')} forecast days refreshed")
        else:
            print(f"[weather] {zone['zone_id']}: {result.get('error', {}).get('message', 'failed')}")


def run(api: str, interval: float, demo_zone: str, demo_rate: float, weather_minutes: float,
        stop: Optional[threading.Event] = None) -> None:
    stop = stop or threading.Event()
    rng = random.Random()
    zones = [z for z in _call(api, "GET", "/zones").get("zones", []) if z.get("enabled", True)]
    if not zones:
        print("[sim] no zones found — seed data first (local_server.py --demo or demo_seed.py)")
        return

    state: Dict[str, float] = {}
    for zone in zones:
        history = _call(api, "GET", f"/zones/{zone['zone_id']}/readings?hours=24").get("readings", [])
        state[zone["zone_id"]] = history[-1]["soil_moisture"] if history else zone["target_moisture"] - 5

    refresh_weather(api, zones)
    next_weather = time.monotonic() + weather_minutes * 60
    irrigate_in: Dict[str, int] = {}
    print(f"[sim] streaming readings for {len(zones)} zones every {interval:g}s (demo zone: {demo_zone})")

    while not stop.is_set():
        for zone in zones:
            zid = zone["zone_id"]
            if zid in irrigate_in:
                irrigate_in[zid] -= 1
                if irrigate_in[zid] <= 0:
                    del irrigate_in[zid]
                    state[zid] = zone["target_moisture"] + rng.uniform(0, 2)
                    print(f"[sim] {zid}: irrigation valve opened → moisture restored to {state[zid]:.1f}%")
            elif zid == demo_zone:
                state[zid] -= demo_rate * rng.uniform(0.8, 1.2)
            else:
                state[zid] -= rng.uniform(0.02, 0.12)
                if state[zid] < zone["moisture_threshold"] + 2:  # keep non-demo zones healthy
                    state[zid] = zone["target_moisture"]

            body = {
                "soil_moisture": round(max(5.0, state[zid]), 1),
                "device_id": _DEVICE_IDS.get(zid, f"{zid}-sensor"),
                **climate(datetime.now(timezone.utc), _TEMP_OFFSETS.get(zid, 0.0), rng),
            }
            result = _call(api, "POST", f"/zones/{zid}/readings", body)
            decision = result.get("decision", {})
            rec = decision.get("recommendation", result.get("error", {}).get("code", "?"))
            note = f"  ALERT {result['alert_id']} → SMS sent" if result.get("alert_id") else ""
            print(f"[sim] {zid}: moisture {body['soil_moisture']:5.1f}%  {rec}{note}")
            if rec == "IRRIGATION_REQUIRED" and zid not in irrigate_in:
                irrigate_in[zid] = 4  # farmer responds to the SMS a few ticks later

        if time.monotonic() >= next_weather:
            refresh_weather(api, zones)
            next_weather = time.monotonic() + weather_minutes * 60
        stop.wait(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="http://localhost:3001", help="API base URL")
    parser.add_argument("--interval", type=float, default=15, help="seconds between readings")
    parser.add_argument("--demo-zone", default=DEMO_ZONE_ID)
    parser.add_argument("--demo-rate", type=float, default=0.9, help="%% moisture lost per tick in the demo zone")
    parser.add_argument("--weather-minutes", type=float, default=30, help="minutes between forecast refreshes")
    args = parser.parse_args()
    try:
        run(args.api, args.interval, args.demo_zone, args.demo_rate, args.weather_minutes)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
