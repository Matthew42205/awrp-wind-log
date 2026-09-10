#!/usr/bin/env python3
"""
AWRP wind logger.

Polls the free Open-Meteo API for modelled wind direction/speed at the
Allerton Waste Recovery Park stack location, and logs hourly readings to
wind_log.csv. For each hour, flags which nearby receptors/villages the
plume is likely being carried towards, based on wind direction.

IMPORTANT - what this is and isn't:
- This is MODELLED wind (UK Met Office UKV 2km model via Open-Meteo), not
  a physical anemometer reading at the site. Treat it as indicative.
- Two heights are logged and flagged SEPARATELY: 10m and 100m. The main
  EfW stack is 70m tall with a hot (130C), high-velocity (15m/s) exit
  (ES Table 10.15) - a buoyant plume like this rises well above the
  physical stack top before it starts travelling downwind, so the wind
  at 100m is a closer proxy for actual plume transport than the 10m
  reading, which is dominated by ground friction and local terrain.
  Don't just look at the 10m columns - the 100m ones are arguably the
  more physically relevant pair for this stack.
- Wind direction is unreliable at low wind speeds. Calm is judged
  separately per height (a common pattern is 10m calm while 100m still
  has a clear, usable direction, since ground friction affects the
  surface far more than 100m up). Calm hours for a given height get no
  downwind receptor assigned for that height, rather than an unreliable
  guess.
- Being "downwind" of the stack is not the same as receiving a harmful
  concentration - that depends on plume rise, atmospheric stability and
  dilution, which this script does not model. Straight-line distance is
  included alongside each flagged receptor as a rough proxy for dilution
  (further = more diluted, all else equal), but it is not a substitute
  for actual dispersion modelling. Use this as a screening indicator to
  prioritise which emissions events are worth closer scrutiny, not as a
  standalone exposure claim.
- receptors.json documents the provenance of every bearing/coordinate
  used - check it before treating any flag as more precise than its
  source actually supports.

Usage:
    python wind_logger.py

Designed to be run on a schedule via GitHub Actions (see
.github/workflows/wind-log.yml), polling once per hour. Open-Meteo's
hourly model output does not update faster than hourly, so polling more
often would not add resolution.
"""

import csv
import json
import math
import os
import sys
from datetime import datetime, timezone

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
RECEPTORS_PATH = os.path.join(HERE, "receptors.json")
CSV_PATH = os.path.join(HERE, "wind_log.csv")

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
MODEL = "ukmo_uk_deterministic_2km"  # UK Met Office UKV 2km model, via Open-Meteo
PAST_DAYS = 3          # look back window each run, to backfill any missed hours
FORECAST_DAYS = 1

CALM_THRESHOLD_MS = 2.0     # below this, direction is flagged unreliable
SECTOR_TOLERANCE_DEG = 22.5  # +/- half-width of the "likely downwind" cone

CSV_FIELDS = [
    "timestamp_utc",
    "wind_from_deg_10m",
    "wind_speed_ms_10m",
    "wind_from_deg_100m",
    "wind_speed_ms_100m",
    "model",
    "calm_flag",
    "plume_bearing_deg_10m",
    "likely_downwind_receptors_10m",
    "plume_bearing_deg_100m",
    "likely_downwind_receptors_100m",
]


def load_receptors():
    with open(RECEPTORS_PATH) as f:
        data = json.load(f)
    stack = data["stack"]
    receptors = []
    for r in data.get("bearing_receptors", []):
        receptors.append({
            "name": r["name"],
            "bearing_deg": r["bearing_deg"],
            "distance_m": r.get("distance_m"),
        })
    for v in data.get("latlon_receptors", []):
        bearing = initial_bearing(stack["lat"], stack["lon"], v["lat"], v["lon"])
        distance = haversine_m(stack["lat"], stack["lon"], v["lat"], v["lon"])
        receptors.append({
            "name": v["name"],
            "bearing_deg": bearing,
            "distance_m": distance,
        })
    return stack, receptors


def initial_bearing(lat1, lon1, lat2, lon2):
    """Great-circle initial bearing in degrees from point 1 to point 2."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    x = math.sin(dlon) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlon)
    theta = math.atan2(x, y)
    return (math.degrees(theta) + 360) % 360


EARTH_RADIUS_M = 6371000.0


def haversine_m(lat1, lon1, lat2, lon2):
    """Straight-line (great-circle) distance in metres between two points."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def angular_diff(a, b):
    """Smallest difference between two bearings, 0-180."""
    d = abs((a - b + 180) % 360 - 180)
    return d


def fetch_wind(stack):
    params = {
        "latitude": stack["lat"],
        "longitude": stack["lon"],
        "hourly": "wind_direction_10m,wind_speed_10m,wind_direction_100m,wind_speed_100m",
        "wind_speed_unit": "ms",
        "timezone": "UTC",
        "past_days": PAST_DAYS,
        "forecast_days": FORECAST_DAYS,
        "models": MODEL,
    }
    resp = requests.get(OPEN_METEO_URL, params=params, timeout=30)
    if resp.status_code != 200:
        # Fall back to best_match if the specific UKMO model isn't available
        # for this run (e.g. transient upstream issue).
        params["models"] = "best_match"
        resp = requests.get(OPEN_METEO_URL, params=params, timeout=30)
        resp.raise_for_status()
        model_used = "best_match"
    else:
        model_used = MODEL
    return resp.json(), model_used


def load_existing_timestamps():
    if not os.path.exists(CSV_PATH):
        return set()
    with open(CSV_PATH, newline="") as f:
        reader = csv.DictReader(f)
        return {row["timestamp_utc"] for row in reader}


def append_rows(rows):
    file_exists = os.path.exists(CSV_PATH)
    with open(CSV_PATH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main():
    stack, receptors = load_receptors()
    data, model_used = fetch_wind(stack)

    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    dir10 = hourly.get("wind_direction_10m", [])
    spd10 = hourly.get("wind_speed_10m", [])
    dir100 = hourly.get("wind_direction_100m", [])
    spd100 = hourly.get("wind_speed_100m", [])

    if not times:
        print("No hourly data returned - check API response / model availability.", file=sys.stderr)
        sys.exit(1)

    existing = load_existing_timestamps()
    now_utc = datetime.now(timezone.utc)

    new_rows = []
    for i, t in enumerate(times):
        # Open-Meteo timestamps are naive local-to-requested-timezone (UTC here)
        ts = t if t.endswith("Z") else t  # keep as-is; timezone=UTC was requested
        if ts in existing:
            continue
        # Skip future/forecast hours beyond "now" - only log observed/analysed hours
        try:
            ts_dt = datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if ts_dt > now_utc:
            continue

        wd10 = dir10[i] if i < len(dir10) else None
        ws10 = spd10[i] if i < len(spd10) else None
        wd100 = dir100[i] if i < len(dir100) else None
        ws100 = spd100[i] if i < len(spd100) else None

        if wd10 is None or ws10 is None:
            continue

        # Calm is judged separately per height - surface wind (10m) is far
        # more affected by ground friction than 100m, so it's common for
        # 10m to be calm while 100m (closer to the plume's actual transport
        # height, given this stack's height and buoyant, hot exit - see
        # module docstring) still has a clear, usable direction.
        calm_10m = ws10 < CALM_THRESHOLD_MS
        calm_100m = (ws100 is None) or (ws100 < CALM_THRESHOLD_MS)

        plume_bearing_10m = (wd10 + 180) % 360
        plume_bearing_100m = (wd100 + 180) % 360 if wd100 is not None else None

        def find_downwind(plume_bearing):
            if plume_bearing is None:
                return []
            hits = [r for r in receptors
                    if angular_diff(plume_bearing, r["bearing_deg"]) <= SECTOR_TOLERANCE_DEG]
            # Nearest first - most relevant for real-world dilution/impact reasoning
            hits.sort(key=lambda r: r["distance_m"] if r["distance_m"] is not None else float("inf"))
            return hits

        def format_receptor(r):
            if r["distance_m"] is not None:
                return f"{r['name']} ({r['distance_m']/1000:.1f}km)"
            return r["name"]

        downwind_10m = [] if calm_10m else find_downwind(plume_bearing_10m)
        downwind_100m = [] if calm_100m else find_downwind(plume_bearing_100m)

        new_rows.append({
            "timestamp_utc": ts,
            "wind_from_deg_10m": wd10,
            "wind_speed_ms_10m": ws10,
            "wind_from_deg_100m": wd100,
            "wind_speed_ms_100m": ws100,
            "model": model_used,
            "calm_flag": calm_10m,
            "plume_bearing_deg_10m": round(plume_bearing_10m, 1),
            "likely_downwind_receptors_10m": ";".join(format_receptor(r) for r in downwind_10m) if downwind_10m else "",
            "plume_bearing_deg_100m": round(plume_bearing_100m, 1) if plume_bearing_100m is not None else "",
            "likely_downwind_receptors_100m": ";".join(format_receptor(r) for r in downwind_100m) if downwind_100m else "",
        })

    if new_rows:
        append_rows(new_rows)
        print(f"Appended {len(new_rows)} new hourly rows (model: {model_used}).")
    else:
        print("No new rows to append - already up to date.")


if __name__ == "__main__":
    main()
