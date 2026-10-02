from fastapi import APIRouter, Query, HTTPException
from app.db import get_client

router = APIRouter()


def _hex_ids_for_city(db, city_id: str | None):
    if not city_id:
        return None
    rows = db.table("hex_zones").select("hex_id").eq("city_id", city_id).execute().data
    return [r["hex_id"] for r in rows]


@router.get("/current")
def current(city_id: str | None = Query(None), bbox: str | None = Query(None)):
    """Latest cached predictions, horizon = 0."""
    db = get_client()
    hex_ids = _hex_ids_for_city(db, city_id)
    q = db.table("predictions").select("*").eq("horizon_hours", 0)
    if hex_ids is not None:
        q = q.in_("hex_id", hex_ids)
    resp = q.order("generated_at", desc=True).limit(5000).execute()
    return {"predictions": resp.data}


@router.get("/forecast")
def forecast(
    city_id: str | None = Query(None),
    bbox: str | None = Query(None),
    horizon: int = Query(1, description="1, 3, or 6"),
):
    if horizon not in (1, 3, 6):
        raise HTTPException(400, "horizon must be 1, 3, or 6")
    db = get_client()
    hex_ids = _hex_ids_for_city(db, city_id)
    q = db.table("predictions").select("*").eq("horizon_hours", horizon)
    if hex_ids is not None:
        q = q.in_("hex_id", hex_ids)
    resp = q.order("generated_at", desc=True).limit(5000).execute()
    return {"predictions": resp.data}


@router.get("/hex/{hex_id}")
def hex_detail(hex_id: str):
    """Full detail for a single zone: current + all horizons + uncertainty."""
    db = get_client()
    resp = (
        db.table("predictions")
        .select("*")
        .eq("hex_id", hex_id)
        .order("generated_at", desc=True)
        .limit(4)  # one row per horizon (0/1/3/6) from the latest run
        .execute()
    )
    if not resp.data:
        raise HTTPException(404, f"No predictions found for hex_id {hex_id}")
    return {"hex_id": hex_id, "predictions": resp.data}
