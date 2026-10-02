"""
Seeds a complete demo pilot city end-to-end:
  cities -> wards -> hex_zones (real H3 grid + synthetic static features)
  -> sensor_readings + satellite_features (synthetic, last few hours)
  -> triggers pipeline/run_inference.py to populate `predictions`

Run once before starting the backend for the first time in demo mode:
    python -m pipeline.seed_demo
"""
import math
import random
import sys
import uuid
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.db import get_client  # noqa: E402
from pipeline.generate_hex_grid import bbox_to_h3_cells, cell_to_geojson  # noqa: E402
from pipeline.synthetic_data import (  # noqa: E402
    DEFAULT_BBOX,
    DEFAULT_CITY_NAME,
    static_features_for_hex,
    dynamic_reading_for_hex,
    utcnow,
)

DEMO_CITY_ID = "demo-city-pune"
N_WARDS = 6
STATION_COUNT = 40
HOURS_OF_HISTORY = 6


def seed_city(db):
    db.table("cities").upsert(
        [
            {
                "id": DEMO_CITY_ID,
                "name": DEFAULT_CITY_NAME,
                "country_code": "IN",
                "bounding_box": list(DEFAULT_BBOX),
            }
        ],
        on_conflict="id",
    ).execute()


def ward_grid(bbox, n_wards):
    """Split the bbox into a small grid of rectangular wards (demo simplification —
    real wards come from municipal boundary shapefiles)."""
    min_lon, min_lat, max_lon, max_lat = bbox
    cols = 3
    rows = math.ceil(n_wards / cols)
    wards = []
    idx = 0
    for r in range(rows):
        for c in range(cols):
            if idx >= n_wards:
                break
            w_min_lon = min_lon + (max_lon - min_lon) * c / cols
            w_max_lon = min_lon + (max_lon - min_lon) * (c + 1) / cols
            w_min_lat = min_lat + (max_lat - min_lat) * r / rows
            w_max_lat = min_lat + (max_lat - min_lat) * (r + 1) / rows
            wards.append(
                {
                    "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{DEMO_CITY_ID}-ward-{idx}")),
                    "city_id": DEMO_CITY_ID,
                    "name": f"Ward {idx + 1}",
                    "bbox": (w_min_lon, w_min_lat, w_max_lon, w_max_lat),
                    "population": random.Random(idx).randint(35000, 210000),
                }
            )
            idx += 1
    return wards


def point_in_bbox(lon, lat, bbox):
    min_lon, min_lat, max_lon, max_lat = bbox
    return min_lon <= lon <= max_lon and min_lat <= lat <= max_lat


def seed_wards(db, bbox):
    wards = ward_grid(bbox, N_WARDS)
    rows = []
    for w in wards:
        min_lon, min_lat, max_lon, max_lat = w["bbox"]
        rows.append(
            {
                "id": w["id"],
                "city_id": w["city_id"],
                "name": w["name"],
                "geom": {
                    "type": "Polygon",
                    "coordinates": [[
                        [min_lon, min_lat], [max_lon, min_lat],
                        [max_lon, max_lat], [min_lon, max_lat], [min_lon, min_lat],
                    ]],
                },
                "population": w["population"],
                "response_infra": {
                    "shelters": [{"name": f"{w['name']} Community Shelter", "lat": (min_lat + max_lat) / 2, "lon": (min_lon + max_lon) / 2}],
                    "water_points": [{"name": f"{w['name']} Water Point", "lat": min_lat + (max_lat - min_lat) * 0.3, "lon": min_lon + (max_lon - min_lon) * 0.3}],
                },
            }
        )
    db.table("wards").upsert(rows, on_conflict="id").execute()
    return wards


def assign_ward(lon, lat, wards):
    for w in wards:
        if point_in_bbox(lon, lat, w["bbox"]):
            return w["id"]
    return None


def seed_hex_zones(db, bbox, wards, resolution=8):
    """Uses a coarser resolution (8, ~0.7km^2) than the PRD's res-9 target for the
    demo seed so the whole pipeline runs in seconds rather than minutes; production
    ingestion should use resolution=9 per pipeline/generate_hex_grid.py's default."""
    cells = bbox_to_h3_cells(*bbox, resolution)
    rows = []
    for cell in sorted(cells):
        polygon_geojson, centroid_geojson, lon, lat = cell_to_geojson(cell)
        static = static_features_for_hex(lon, lat, bbox, seed=hash(cell) % (2**31))
        rows.append(
            {
                "hex_id": cell,
                "city_id": DEMO_CITY_ID,
                "ward_id": assign_ward(lon, lat, wards),
                "geom": polygon_geojson,
                "centroid": centroid_geojson,
                "static_features": static,
            }
        )
    db.table("hex_zones").upsert(rows, on_conflict="hex_id").execute()
    print(f"Seeded {len(rows)} hex zones at H3 resolution {resolution}")
    return rows


def seed_sensor_and_satellite_history(db, hex_rows):
    rng = random.Random(11)
    stations = rng.sample(hex_rows, min(STATION_COUNT, len(hex_rows)))
    now = utcnow()
    sensor_rows, sat_rows = [], []
    for h in range(HOURS_OF_HISTORY, -1, -1):
        dt = now - timedelta(hours=h)
        for i, hx in enumerate(stations):
            reading = dynamic_reading_for_hex(hx["static_features"], dt, rng)
            sensor_rows.append(
                {
                    "source": "CPCB" if i % 2 == 0 else "IMD",
                    "station_id": f"{hx['hex_id']}-station",
                    "hex_id": hx["hex_id"],
                    "recorded_at": dt.isoformat(),
                    "temperature_c": reading["temperature_c"],
                    "humidity_pct": reading["humidity_pct"],
                    "wind_speed_ms": reading["wind_speed_ms"],
                    "wind_dir_deg": reading["wind_dir_deg"],
                }
            )
        for hx in hex_rows:
            reading = dynamic_reading_for_hex(hx["static_features"], dt, rng)
            sat_rows.append(
                {
                    "hex_id": hx["hex_id"],
                    "source": "ERA5_LAND",
                    "recorded_at": dt.isoformat(),
                    "lst_c": reading["lst_c"],
                    "era5_temp_c": reading["temperature_c"],
                    "era5_humidity_pct": reading["humidity_pct"],
                    "era5_wind_speed_ms": reading["wind_speed_ms"],
                    "era5_wind_dir_deg": reading["wind_dir_deg"],
                }
            )
    db.table("sensor_readings").insert(sensor_rows).execute()
    db.table("satellite_features").insert(sat_rows).execute()
    print(f"Seeded {len(sensor_rows)} sensor readings and {len(sat_rows)} satellite feature rows")


def log_pipeline_runs(db):
    now = utcnow()
    for job_type, source in [
        ("ingestion", "CPCB"),
        ("ingestion", "IMD"),
        ("ingestion", "ERA5_LAND"),
        ("ingestion", "SENTINEL2"),
    ]:
        db.table("pipeline_runs").insert(
            {
                "job_type": job_type,
                "source": source,
                "status": "success",
                "started_at": (now - timedelta(minutes=5)).isoformat(),
                "completed_at": now.isoformat(),
                "metrics": {"rows_ingested": STATION_COUNT, "data_source": "synthetic-demo"},
            }
        ).execute()


def main():
    db = get_client()
    print("Seeding demo city, wards, and hex grid...")
    seed_city(db)
    wards = seed_wards(db, DEFAULT_BBOX)
    hex_rows = seed_hex_zones(db, DEFAULT_BBOX, wards)
    seed_sensor_and_satellite_history(db, hex_rows)
    log_pipeline_runs(db)
    print("Demo data seeded. Now run: python -m pipeline.run_inference")


if __name__ == "__main__":
    main()
