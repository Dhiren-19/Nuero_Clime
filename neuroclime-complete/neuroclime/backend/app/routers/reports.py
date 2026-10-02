"""
/v1/reports — F9 Automated Report Export (authority view).

Per the project's own cut-list ("keep CSV only, add PDF later"), this
generates CSV reports synchronously (report jobs here are small enough —
one city/ward's current ward ranking — that "async job" collapses to
"instant" without materially changing the contract). A production
implementation with country-scale multi-city reports would move the
`_build_csv` call onto a background worker/queue and leave the polling
`GET /{report_id}` contract exactly as already written here.
"""
import csv
import io
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db import get_client, is_demo_mode
from app.config import settings

router = APIRouter()

REPORTS_DIR = Path(settings.LOCAL_DATA_DIR) / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


class ReportRequest(BaseModel):
    ward_id: str | None = None
    city_id: str | None = None
    period: str = "24h"


def _ward_summary_rows(db, city_id: str | None, ward_id: str | None):
    wards_q = db.table("wards").select("id,name,population,city_id")
    if ward_id:
        wards_q = wards_q.eq("id", ward_id)
    elif city_id:
        wards_q = wards_q.eq("city_id", city_id)
    wards = wards_q.execute().data

    rows = []
    for ward in wards:
        hexes = db.table("hex_zones").select("hex_id").eq("ward_id", ward["id"]).execute().data
        hex_ids = [h["hex_id"] for h in hexes]
        preds = (
            db.table("predictions").select("*").in_("hex_id", hex_ids).eq("horizon_hours", 6).execute().data
            if hex_ids
            else []
        )
        if preds:
            avg_hi = round(sum(p["heat_index_c"] or 0 for p in preds) / len(preds), 2)
            worst = max(preds, key=lambda p: p["heat_index_c"] or 0)
            recommended_action = {
                "extreme": "Activate emergency cooling shelters and water distribution immediately.",
                "danger": "Pre-position water points and open shaded shelters in worst-affected hexes.",
                "caution": "Issue public advisory; monitor for escalation over the forecast window.",
                "safe": "No action needed; continue routine monitoring.",
            }.get(worst["risk_band"], "Monitor.")
        else:
            avg_hi, worst, recommended_action = None, None, "No prediction data available."

        rows.append(
            {
                "ward_id": ward["id"],
                "ward_name": ward["name"],
                "population": ward.get("population"),
                "hex_count": len(hex_ids),
                "avg_heat_index_6h_c": avg_hi,
                "peak_risk_band_6h": worst["risk_band"] if worst else None,
                "peak_hex_id": worst["hex_id"] if worst else None,
                "recommended_action": recommended_action,
            }
        )
    return rows


def _build_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    if not rows:
        buf.write("no_data\ntrue\n")
        return buf.getvalue()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


@router.post("/generate")
def generate_report(req: ReportRequest):
    db = get_client()
    report_id = str(uuid.uuid4())

    rows = _ward_summary_rows(db, req.city_id, req.ward_id)
    csv_text = _build_csv(rows)

    file_name = f"{report_id}.csv"
    file_url = None

    if is_demo_mode():
        (REPORTS_DIR / file_name).write_text(csv_text)
        file_url = f"/reports/{file_name}"
    else:
        try:
            db.storage.from_("reports").upload(file_name, csv_text.encode("utf-8"))
            file_url = db.storage.from_("reports").get_public_url(file_name)
        except Exception as e:  # pragma: no cover - network/storage errors
            raise HTTPException(500, f"Failed to upload report to storage: {e}")

    db.table("reports").insert(
        {
            "id": report_id,
            "ward_id": req.ward_id,
            "format": "csv",
            "file_url": file_url,
        }
    ).execute()
    return {"report_id": report_id, "status": "complete", "file_url": file_url, "rows": len(rows)}


@router.get("/{report_id}")
def get_report(report_id: str):
    db = get_client()
    resp = db.table("reports").select("*").eq("id", report_id).execute()
    if not resp.data:
        raise HTTPException(404, "report not found")
    return resp.data[0]
