import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db import get_client

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # repo root, for `pipeline` import
from pipeline import model as model_module  # noqa: E402
from pipeline.heat_index import heat_index_c, risk_band_dict  # noqa: E402
from pipeline.synthetic_data import utcnow  # noqa: E402

router = APIRouter()


class ScenarioRequest(BaseModel):
    hex_id: str
    modified_features: dict  # e.g. {"ndvi": 0.65, "building_density_pct": 0.2}
    horizon_hours: int = 0


@router.post("")
def run_scenario(req: ScenarioRequest):
    """
    Low-QPS, on-demand endpoint (TRD 2.3.2): re-runs inference for a single
    hex with hypothetical feature values (e.g. more tree cover) and returns
    the predicted temperature delta versus the current baseline. This calls
    the same `pipeline.model.predict` function the batch inference job uses,
    just for one hex.
    """
    db = get_client()
    baseline = db.table("hex_zones").select("*").eq("hex_id", req.hex_id).execute().data
    if not baseline:
        raise HTTPException(404, f"hex_id {req.hex_id} not found")
    baseline_features = baseline[0].get("static_features") or {}

    recent = (
        db.table("sensor_readings")
        .select("temperature_c,humidity_pct")
        .eq("hex_id", req.hex_id)
        .order("recorded_at", desc=True)
        .limit(1)
        .execute()
        .data
    )
    recent_temp_c = recent[0]["temperature_c"] if recent else 30.0
    recent_humidity_pct = recent[0]["humidity_pct"] if recent else 55.0

    now = utcnow()
    baseline_pred = model_module.predict(baseline_features, recent_temp_c, recent_humidity_pct, now, req.horizon_hours)

    modified_features = {**baseline_features, **req.modified_features}
    delta_temp_c = model_module.scenario_delta_c(baseline_features, modified_features)

    scenario_pred = {
        "pred_temp_c": round(baseline_pred["pred_temp_c"] + delta_temp_c, 2),
        "pred_temp_uncertainty_c": baseline_pred["pred_temp_uncertainty_c"],
        "pred_humidity_pct": baseline_pred["pred_humidity_pct"],
    }
    scenario_hi = heat_index_c(scenario_pred["pred_temp_c"], scenario_pred["pred_humidity_pct"])

    record = {
        "hex_id": req.hex_id,
        "baseline_features": baseline_features,
        "modified_features": req.modified_features,
        "predicted_delta_temp_c": delta_temp_c,
    }
    db.table("scenarios").insert(record).execute()

    return {
        "hex_id": req.hex_id,
        "horizon_hours": req.horizon_hours,
        "baseline": baseline_pred,
        "scenario": scenario_pred,
        "predicted_delta_temp_c": delta_temp_c,
        "scenario_risk_band": risk_band_dict(scenario_hi),
    }
