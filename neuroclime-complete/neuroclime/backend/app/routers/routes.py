"""
/v1/routes/coolest — F8 Coolest Route Planner (P2). See TRD 2.3.2 and
pipeline/coolest_route.py for the actual routing algorithm.
"""
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from app.db import get_client

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from pipeline.coolest_route import find_coolest_route  # noqa: E402

router = APIRouter()


@router.get("")
def coolest_route(
    origin: str = Query(..., description="lon,lat"),
    destination: str = Query(..., description="lon,lat"),
    city_id: str | None = Query(None),
):
    try:
        o_lon, o_lat = map(float, origin.split(","))
        d_lon, d_lat = map(float, destination.split(","))
    except ValueError:
        raise HTTPException(400, "origin/destination must be 'lon,lat'")

    db = get_client()
    hz_q = db.table("hex_zones").select("hex_id,centroid,city_id")
    if city_id:
        hz_q = hz_q.eq("city_id", city_id)
    hex_zones = hz_q.execute().data

    preds = db.table("predictions").select("hex_id,heat_index_c").eq("horizon_hours", 0).execute().data

    try:
        result = find_coolest_route(hex_zones, preds, (o_lon, o_lat), (d_lon, d_lat))
    except ValueError as e:
        raise HTTPException(404, str(e))

    return result
