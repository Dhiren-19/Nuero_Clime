"""
/v1/alerts — F5 Personalized Alerts.

Users subscribe a home/work hex; pipeline/run_inference.py's `queue_alerts`
step writes a row here whenever that hex crosses into Danger/Extreme at the
current horizon. This router covers subscribing and reading the user's own
queued alerts (Realtime push delivery from here is a Supabase Realtime
subscription on the client — see TRD 2.3.1 — not something this REST layer
needs to implement itself).
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.db import get_client
from app.auth import get_current_user

router = APIRouter()


class SubscribeRequest(BaseModel):
    home_hex_id: str | None = None
    work_hex_id: str | None = None
    preferred_language: str = "en"


@router.post("/subscribe")
def subscribe(req: SubscribeRequest, user=Depends(get_current_user)):
    """
    PRD 1.4 privacy note: only a hex_id (~0.1 km^2 zone), never precise
    coordinates, is persisted here, and only once the user explicitly opts
    in to zone-based alerts.
    """
    db = get_client()
    user_id = user.get("sub")
    db.table("users").upsert(
        [
            {
                "id": user_id,
                "role": user.get("role", "citizen"),
                "home_hex_id": req.home_hex_id,
                "work_hex_id": req.work_hex_id,
                "preferred_language": req.preferred_language,
            }
        ],
        on_conflict="id",
    ).execute()
    return {"status": "subscribed", "user_id": user_id}


@router.get("")
def list_alerts(user=Depends(get_current_user)):
    db = get_client()
    user_id = user.get("sub")
    resp = (
        db.table("alerts")
        .select("*")
        .eq("user_id", user_id)
        .order("triggered_at", desc=True)
        .limit(20)
        .execute()
    )
    return {"alerts": resp.data}
