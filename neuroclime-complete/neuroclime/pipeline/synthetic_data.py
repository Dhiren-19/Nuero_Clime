"""
Synthetic but physically-plausible data generator.

None of CPCB, IMD, MOSDAC, NASA Earthdata, Copernicus CDS, or Google Earth
Engine can be reached from here without registered account credentials
(see .env). Rather than leaving the demo empty, this module generates
static land-cover features and dynamic temperature/humidity readings that
follow the *real, well-documented physical relationship* the whole product
is built around: less vegetation + more built-up density + closer to the
urban core => higher land-surface and air temperature (the urban heat
island effect), plus a normal diurnal cycle. This makes it possible to:

  1. See a genuinely heterogeneous, non-random hex map (dense concrete
     cores read hotter than parks/water, exactly as NeuroClime claims).
  2. Train and evaluate the baseline model on data with real signal in it,
     not noise (the leave-station-out MAE/RMSE numbers actually mean
     something as a baseline check).
  3. Swap this module out for `ingest_*.py` (real API pulls) with no
     changes needed to the model or API layers, once real credentials are
     added to .env.

Every value produced here should be treated as SYNTHETIC / DEMO DATA — the
admin dashboard and API responses label it accordingly (see
`pipeline_runs.metrics.data_source`).
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone

# Pune-ish default bounding box (min_lon, min_lat, max_lon, max_lat)
DEFAULT_BBOX = (73.74, 18.44, 73.98, 18.62)
DEFAULT_CITY_NAME = "Demo City (Pune bbox)"


def _urban_core(bbox):
    min_lon, min_lat, max_lon, max_lat = bbox
    return ((min_lon + max_lon) / 2, (min_lat + max_lat) / 2)


def static_features_for_hex(lon: float, lat: float, bbox, seed: int) -> dict:
    """Deterministic pseudo-random static land-cover features for one hex."""
    rng = random.Random(seed)
    core_lon, core_lat = _urban_core(bbox)
    min_lon, min_lat, max_lon, max_lat = bbox
    span = max(max_lon - min_lon, max_lat - min_lat)

    dist = math.hypot(lon - core_lon, lat - core_lat) / (span / 2 + 1e-9)  # ~0 (core) .. ~1.4 (edge)
    dist = min(dist, 1.4)
    urbanization = max(0.0, 1.0 - dist / 1.2)  # 1 = dense core, 0 = far periphery

    ndvi = round(max(0.02, min(0.85, rng.gauss(0.55 - 0.4 * urbanization, 0.08))), 3)
    ndbi = round(max(-0.3, min(0.6, rng.gauss(-0.1 + 0.45 * urbanization, 0.07))), 3)
    albedo = round(max(0.05, min(0.35, rng.gauss(0.18 - 0.04 * urbanization, 0.03))), 3)
    building_density = round(max(0.0, min(1.0, rng.gauss(0.15 + 0.7 * urbanization, 0.1))), 3)
    elevation_m = round(max(500, rng.gauss(560 - 20 * urbanization, 12)), 1)

    if urbanization > 0.7:
        lcz = "LCZ2_compact_midrise"
    elif urbanization > 0.4:
        lcz = "LCZ6_open_lowrise"
    elif ndvi > 0.6:
        lcz = "LCZB_scattered_trees"
    else:
        lcz = "LCZD_low_plants"

    return {
        "ndvi": ndvi,
        "ndbi": ndbi,
        "albedo": albedo,
        "building_density_pct": building_density,
        "elevation_m": elevation_m,
        "lcz_class": lcz,
        "urbanization_index": round(urbanization, 3),  # convenience derived field, not in TRD schema
    }


def diurnal_base_temp_c(hour: float, day_of_year: int) -> float:
    """A smooth daily temperature curve with a mild seasonal offset."""
    seasonal = 4.0 * math.sin(2 * math.pi * (day_of_year - 80) / 365.0)  # peaks ~spring/summer for N. hemisphere
    daily = -6.0 * math.cos(2 * math.pi * (hour - 3) / 24.0)  # trough ~4-5am, peak ~15-16h
    return 27.0 + seasonal + daily


def dynamic_reading_for_hex(static: dict, dt: datetime, rng: random.Random) -> dict:
    """Temperature/humidity at a given hex + timestamp, driven by UHI physics."""
    hour = dt.hour + dt.minute / 60.0
    base_temp = diurnal_base_temp_c(hour, dt.timetuple().tm_yday)

    uhi_boost = static["urbanization_index"] * 3.5 - static["ndvi"] * 1.5
    noise = rng.gauss(0, 0.4)
    temp_c = round(base_temp + uhi_boost + noise, 2)

    base_humidity = 78 - 1.6 * (temp_c - 27)  # inverse-ish relationship with temp
    humidity_pct = round(max(15, min(95, base_humidity - static["urbanization_index"] * 6 + rng.gauss(0, 3))), 1)

    wind_speed_ms = round(max(0.2, rng.gauss(2.2 - static["urbanization_index"] * 0.6, 0.6)), 2)
    wind_dir_deg = round(rng.uniform(0, 360), 1)

    lst_c = round(temp_c + static["urbanization_index"] * 2.0 - static["ndvi"] * 1.0 + rng.gauss(0, 0.3), 2)

    return {
        "temperature_c": temp_c,
        "humidity_pct": humidity_pct,
        "wind_speed_ms": wind_speed_ms,
        "wind_dir_deg": wind_dir_deg,
        "lst_c": lst_c,
    }


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
