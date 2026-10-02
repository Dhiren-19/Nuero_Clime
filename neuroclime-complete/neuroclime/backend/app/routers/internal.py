from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.db import get_client
from app.auth import require_role

router = APIRouter()


@router.get("/status")
def pipeline_status(user=Depends(require_role("admin"))):
    db = get_client()
    resp = (
        db.table("pipeline_runs")
        .select("*")
        .order("started_at", desc=True)
        .limit(50)
        .execute()
    )
    return {"runs": resp.data}


class TriggerRequest(BaseModel):
    job_type: str  # 'ingestion' | 'inference'
    source: str | None = None


@router.post("/trigger")
def trigger_job(req: TriggerRequest, user=Depends(require_role("admin"))):
    """
    Prototype: just logs a 'running' pipeline_runs row. Wire this up to
    actually kick off the relevant ingestion/inference script (subprocess,
    queue message, or GitHub Actions workflow_dispatch) once those exist.
    """
    db = get_client()
    db.table("pipeline_runs").insert(
        {"job_type": req.job_type, "source": req.source, "status": "running"}
    ).execute()
    return {"status": "triggered", "job_type": req.job_type, "source": req.source}
