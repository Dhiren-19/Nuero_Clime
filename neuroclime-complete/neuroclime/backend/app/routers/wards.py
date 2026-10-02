from fastapi import APIRouter, Query, Depends, HTTPException
from app.db import get_client
from app.auth import require_role

router = APIRouter()


@router.get("/ranking")
def ward_ranking(city_id: str, user=Depends(require_role("authority", "admin"))):
    """
    Ward list sorted by predicted exposure score for the next 6h.
    Exposure score = population-weighted mean risk of hexes in the ward.
    Prototype version: computed on the fly from `predictions` + `wards`.
    A production version should pre-materialize this in a view/cron job
    to hit the <1s dashboard budget from the NFRs.
    """
    db = get_client()
    wards_resp = db.table("wards").select("id,name,population").eq("city_id", city_id).execute()
    if not wards_resp.data:
        raise HTTPException(404, "No wards found for city_id")

    ranking = []
    for ward in wards_resp.data:
        hexes = (
            db.table("hex_zones").select("hex_id").eq("ward_id", ward["id"]).execute().data
        )
        hex_ids = [h["hex_id"] for h in hexes]
        if not hex_ids:
            continue
        preds = (
            db.table("predictions")
            .select("heat_index_c")
            .in_("hex_id", hex_ids)
            .eq("horizon_hours", 6)
            .execute()
            .data
        )
        if not preds:
            continue
        avg_heat_index = sum(p["heat_index_c"] or 0 for p in preds) / len(preds)
        exposure_score = avg_heat_index * (ward.get("population") or 1)
        ranking.append(
            {
                "ward_id": ward["id"],
                "name": ward["name"],
                "avg_heat_index_c": round(avg_heat_index, 2),
                "exposure_score": round(exposure_score, 2),
            }
        )

    ranking.sort(key=lambda r: r["exposure_score"], reverse=True)
    return {"ranking": ranking}
