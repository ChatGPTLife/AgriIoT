"""
Demo data seeder.

Creates four zones and seven days of realistic sensor history (a reading
every 30 minutes with a day/night temperature cycle), irrigation decisions
produced by the real irrigation engine, and the alerts that history would
have raised (already acknowledged).

The history is shaped so that "north-field" is drying out right now: it is
a few percent above its threshold, and its last alert is older than the
alert cooldown, so the sensor simulator can push it below the threshold
during a live demo and trigger an automatic SMS.

Usage:
    python demo_seed.py            # seeds the tables named in ../.env (real AWS)
    python local_server.py --demo  # seeds the in-memory tables automatically
"""
from __future__ import annotations

import json
import math
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

DEMO_ZONE_ID = "north-field"

# Irrigation events are given as "hours ago". Moisture falls linearly at
# `dry_rate` %/hour after each event; an alert is raised wherever it would
# have crossed the threshold before the next irrigation.
ZONES: List[Dict[str, Any]] = [
    {
        "zone": {
            "zone_id": "north-field", "name": "North Field", "crop_type": "wheat", "soil_type": "loam",
            "latitude": 18.5204, "longitude": 73.8567, "moisture_threshold": 30.0, "target_moisture": 45.0,
        },
        "device_id": "nf-soil-01", "dry_rate": 0.75, "irrigations": [166, 140, 114, 86, 62, 38, 14], "temp_offset": 0.5,
    },
    {
        "zone": {
            "zone_id": "river-plot", "name": "River Plot", "crop_type": "sugarcane", "soil_type": "clay",
            "latitude": 18.6011, "longitude": 73.7641, "moisture_threshold": 40.0, "target_moisture": 60.0,
        },
        "device_id": "rp-soil-02", "dry_rate": 0.6, "irrigations": [150, 115, 80, 50, 22], "temp_offset": -0.8,
    },
    {
        "zone": {
            "zone_id": "mango-orchard", "name": "Mango Orchard", "crop_type": "mango", "soil_type": "sandy loam",
            "latitude": 18.4529, "longitude": 73.9010, "moisture_threshold": 25.0, "target_moisture": 40.0,
        },
        "device_id": "mo-soil-03", "dry_rate": 0.3, "irrigations": [168, 110, 40], "temp_offset": 1.2,
    },
    {
        "zone": {
            "zone_id": "greenhouse-b", "name": "Greenhouse B", "crop_type": "tomato", "soil_type": "red soil",
            "latitude": 18.5590, "longitude": 73.8075, "moisture_threshold": 35.0, "target_moisture": 55.0,
        },
        "device_id": "gh-soil-04", "dry_rate": 0.5, "irrigations": [168, 144, 120, 96, 72, 48, 24], "temp_offset": 2.5,
    },
]

HISTORY_HOURS = 168
STEP_MINUTES = 30
IST = timezone(timedelta(hours=5, minutes=30))


def climate(ts: datetime, temp_offset: float, rng: random.Random) -> Dict[str, float]:
    """Day/night cycle peaking at 14:00 local time."""
    local_hour = ts.astimezone(IST).hour + ts.astimezone(IST).minute / 60
    wave = math.sin(2 * math.pi * (local_hour - 8) / 24)
    temperature = 27.0 + temp_offset + 6.0 * wave + rng.uniform(-0.6, 0.6)
    humidity = 62.0 - 18.0 * wave + rng.uniform(-3, 3)
    return {"temperature": round(temperature, 1), "humidity": round(max(15, min(98, humidity)), 0)}


def moisture_at(hours_ago: float, spec: Dict[str, Any], rng: random.Random) -> float:
    target = spec["zone"]["target_moisture"]
    previous = [h for h in spec["irrigations"] if h >= hours_ago]
    since = (min(previous) - hours_ago) if previous else (HISTORY_HOURS - hours_ago + 6)
    value = target + 1.5 - spec["dry_rate"] * since + rng.uniform(-0.5, 0.5)
    return round(max(5.0, min(95.0, value)), 1)


def build_history(now: datetime, seed: int = 7) -> Dict[str, List[Dict[str, Any]]]:
    from src.services.irrigation_engine import IrrigationInputs, evaluate

    rng = random.Random(seed)
    out: Dict[str, List[Dict[str, Any]]] = {"zones": [], "readings": [], "decisions": [], "alerts": []}

    for spec in ZONES:
        zone = dict(spec["zone"], enabled=True)
        created = (now - timedelta(days=21)).isoformat()
        zone.update(created_at=created, updated_at=created)
        out["zones"].append(zone)

        alerted_cycle = set()
        steps = HISTORY_HOURS * 60 // STEP_MINUTES
        for i in range(steps, 0, -1):
            ts = now - timedelta(minutes=i * STEP_MINUTES)
            hours_ago = i * STEP_MINUTES / 60
            moisture = moisture_at(hours_ago, spec, rng)
            weather = climate(ts, spec["temp_offset"], rng)
            reading_id = f"rdg-{rng.getrandbits(48):012x}"
            out["readings"].append({
                "reading_id": reading_id, "zone_id": zone["zone_id"], "device_id": spec["device_id"],
                "soil_moisture": moisture, **weather,
                "timestamp": ts.isoformat(), "created_at": ts.isoformat(),
            })

            cycle = min([h for h in spec["irrigations"] if h >= hours_ago], default=None)
            crossed = moisture < zone["moisture_threshold"] and cycle not in alerted_cycle
            if i % 6 != 0 and not crossed:  # decisions every 3h, plus at threshold crossings
                continue

            decision = json.loads(evaluate(IrrigationInputs(
                zone_id=zone["zone_id"], soil_moisture=moisture,
                moisture_threshold=zone["moisture_threshold"], target_moisture=zone["target_moisture"],
                forecast_rainfall_mm=0.0, rain_probability=rng.choice([0.0, 5.0, 10.0, 20.0]),
                crop_type=zone["crop_type"], soil_type=zone["soil_type"], reading_id=reading_id, **weather,
            )).model_dump_json())
            decision["evaluated_at"] = ts.isoformat()
            out["decisions"].append(decision)

            if crossed:
                alerted_cycle.add(cycle)
                out["alerts"].append({
                    "alert_id": f"alert-{rng.getrandbits(48):012x}",
                    "zone_id": zone["zone_id"], "zone_name": zone["name"],
                    "created_at": ts.isoformat(),
                    "status": "acknowledged",
                    "acknowledged_at": (ts + timedelta(minutes=rng.randint(12, 55))).isoformat(),
                    "urgency": decision["urgency"], "reason": decision["reason"],
                    "soil_moisture": moisture, "threshold": zone["moisture_threshold"],
                    "expected_rainfall_mm": 0.0, "rain_probability": decision.get("rain_probability") or 0.0,
                })
    return out


def seed(now: datetime | None = None) -> Dict[str, int]:
    from src.repositories.base import get_table
    from src.repositories.irrigation import RECORD_TYPE
    from src.utils.config import get_config
    from src.utils.dynamo_serialization import to_dynamo

    config = get_config()
    data = build_history(now or datetime.now(timezone.utc))
    targets = [
        (config.zones_table, data["zones"]),
        (config.readings_table, data["readings"]),
        (config.irrigation_decisions_table, [dict(d, record_type=RECORD_TYPE) for d in data["decisions"]]),
        (config.alerts_table, data["alerts"]),
    ]
    for table_name, items in targets:
        with get_table(table_name).batch_writer() as batch:
            for item in items:
                batch.put_item(Item=to_dynamo(item))
    return {k: len(v) for k, v in data.items()}


if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from local_server import _load_dotenv  # noqa: E402

    _load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    print("Seeded:", seed())
