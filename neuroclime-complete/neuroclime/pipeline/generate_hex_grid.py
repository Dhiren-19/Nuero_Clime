"""
Generate an H3 hex grid covering a city's bounding box and prepare rows
for the `hex_zones` table (TRD 2.2).

H3 resolution 9 gives hexagons of ~0.1 km2 average area, matching the
PRD's "every ~0.1 km2" requirement.

Usage:
    python generate_hex_grid.py --city "Pune" \
        --bbox 73.74,18.44,73.98,18.62 \
        --city-id <uuid-from-cities-table> \
        --out hex_zones.csv

Then either:
  a) load hex_zones.csv into Supabase via the dashboard's table import, or
  b) call push_to_supabase() below once SUPABASE_URL/SERVICE_KEY are set.

bbox format: min_lon,min_lat,max_lon,max_lat
"""
import argparse
import csv
import json
import sys

import h3
from shapely.geometry import Polygon, mapping

H3_RESOLUTION = 9  # ~0.1 km^2 average hex area


def bbox_to_h3_cells(min_lon: float, min_lat: float, max_lon: float, max_lat: float, resolution: int):
    """Return the set of H3 cell indices covering a lon/lat bounding box."""
    # h3.polygon_to_cells expects (lat, lon) ring order
    boundary = [
        (min_lat, min_lon),
        (min_lat, max_lon),
        (max_lat, max_lon),
        (max_lat, min_lon),
    ]
    h3_shape = h3.LatLngPoly(boundary)
    return h3.polygon_to_cells(h3_shape, resolution)


def cell_to_geom(cell: str):
    """Return (polygon_wkt, centroid_wkt) for an H3 cell."""
    boundary = h3.cell_to_boundary(cell)  # list of (lat, lon)
    lon_lat_ring = [(lon, lat) for lat, lon in boundary]
    lon_lat_ring.append(lon_lat_ring[0])  # close ring
    poly = Polygon(lon_lat_ring)
    lat, lon = h3.cell_to_latlng(cell)
    return poly.wkt, f"POINT({lon} {lat})"


def cell_to_geojson(cell: str):
    """Return (polygon_geojson_dict, centroid_geojson_dict, lon, lat) for an H3 cell.
    Used by the local demo store and the frontend map (GeoJSON, not WKT)."""
    boundary = h3.cell_to_boundary(cell)  # list of (lat, lon)
    ring = [[lon, lat] for lat, lon in boundary]
    ring.append(ring[0])
    lat, lon = h3.cell_to_latlng(cell)
    polygon = {"type": "Polygon", "coordinates": [ring]}
    centroid = {"type": "Point", "coordinates": [lon, lat]}
    return polygon, centroid, lon, lat


def build_rows(city_id: str, cells):
    rows = []
    for cell in sorted(cells):
        poly_wkt, centroid_wkt = cell_to_geom(cell)
        rows.append(
            {
                "hex_id": cell,
                "city_id": city_id,
                "ward_id": "",  # fill in later via spatial join against `wards`
                "geom": poly_wkt,
                "centroid": centroid_wkt,
                "static_features": json.dumps({}),  # populated by satellite pipeline
            }
        )
    return rows


def write_csv(rows, out_path: str):
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def push_to_supabase(rows, batch_size: int = 500):
    """Optional: insert rows directly via the Supabase client (service role)."""
    import os
    from supabase import create_client

    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    db = create_client(url, key)

    for row in rows:
        if row["ward_id"] == "":
            row["ward_id"] = None

    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        db.table("hex_zones").upsert(batch, on_conflict="hex_id").execute()
        print(f"Upserted {i + len(batch)}/{len(rows)}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", required=True)
    parser.add_argument("--bbox", required=True, help="min_lon,min_lat,max_lon,max_lat")
    parser.add_argument("--city-id", required=True, help="UUID of the row already in `cities`")
    parser.add_argument("--resolution", type=int, default=H3_RESOLUTION)
    parser.add_argument("--out", default="hex_zones.csv")
    parser.add_argument("--push", action="store_true", help="also insert directly into Supabase")
    args = parser.parse_args()

    min_lon, min_lat, max_lon, max_lat = map(float, args.bbox.split(","))
    cells = bbox_to_h3_cells(min_lon, min_lat, max_lon, max_lat, args.resolution)
    print(f"{args.city}: generated {len(cells)} hex cells at resolution {args.resolution}")

    rows = build_rows(args.city_id, cells)
    write_csv(rows, args.out)
    print(f"Wrote {len(rows)} rows to {args.out}")

    if args.push:
        push_to_supabase(rows)


if __name__ == "__main__":
    main()
