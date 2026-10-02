from fastapi import APIRouter, Query
from app.db import get_client

router = APIRouter()


@router.get("")
def get_hexzones(city_id: str | None = Query(None), bbox: str | None = Query(None)):
    """
    Returns hex grid geometries + static features for a bounding box or city_id.
    bbox format (if used): "min_lon,min_lat,max_lon,max_lat"
    """
    db = get_client()
    q = db.table("hex_zones").select("hex_id,ward_id,geom,centroid,static_features")
    if city_id:
        q = q.eq("city_id", city_id)
    # NOTE: bbox spatial filtering is best done via a Postgres RPC
    # (ST_Intersects) rather than the REST filter builder — see
    # infra/rpc_bbox_filter.sql for a starter function once you add it.
    resp = q.execute()
    return {"hex_zones": resp.data}
