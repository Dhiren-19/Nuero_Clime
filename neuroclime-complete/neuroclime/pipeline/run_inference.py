"""
Batch inference job (TRD 2.1 GRAPH -> MODEL -> DERIVE -> PRED, and TRD 1.4
performance requirement: "Inference pipeline ... must complete within a
15-minute refresh cycle"; TRD 2.3.2: "no live model inference in the request
path except /v1/scenarios").

For every hex zone in a city:
  1. Take the most recent sensor/satellite reading as the "recent" features.
  2. Predict temp_c/humidity_pct at horizons 0, 1, 3, 6h with the trained
     model (pipeline/model.py).
  3. Derive heat_index_c and risk_band (pipeline/heat_index.py).
  4. Upsert one row per (hex_id, horizon) into `predictions`.
  5. Check each user's home/work hex against the fresh Danger/Extreme
     predictions and queue an alert (F5).
  6. Log a `pipeline_runs` row with basic status/metrics (F12's admin view).

Run manually:
    python -m pipeline.run_inference [--city-id demo-city-pune]

In production this is the job a cron/GitHub Actions workflow calls every
INFERENCE_REFRESH_MINUTES (see .env), per TRD 2.4 CI/CD notes.
"""
import argparse
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.db import get_client  # noqa: E402
from app.config import settings  # noqa: E402
from pipeline import model as model_module  # noqa: E402
from pipeline.heat_index import heat_index_c, risk_band_dict, risk_band_for  # noqa: E402
from pipeline.synthetic_data import utcnow  # noqa: E402
from pipeline.bhashini import translate  # noqa: E402

HORIZONS = (0, 1, 3, 6)
ALERT_TRIGGER_BANDS = {"danger", "extreme"}


def latest_reading_for_hex(db, hex_id: str):
    """Most recent sensor reading for this hex; falls back to the most recent
    satellite/ERA5 feature row if no ground station is mapped to this hex."""
    sensor = (
        db.table("sensor_readings")
        .select("*")
        .eq("hex_id", hex_id)
        .order("recorded_at", desc=True)
        .limit(1)
        .execute()
        .data
    )
    if sensor:
        return sensor[0]["temperature_c"], sensor[0]["humidity_pct"]

    sat = (
        db.table("satellite_features")
        .select("*")
        .eq("hex_id", hex_id)
        .order("recorded_at", desc=True)
        .limit(1)
        .execute()
        .data
    )
    if sat:
        return sat[0].get("era5_temp_c", 30.0), sat[0].get("era5_humidity_pct", 50.0)

    return 30.0, 50.0  # last-resort default so the pipeline never blocks (TRD 1.4 reliability)


def run(city_id: str | None = None):
    db = get_client()
    started_at = utcnow()

    q = db.table("hex_zones").select("hex_id,city_id,static_features")
    if city_id:
        q = q.eq("city_id", city_id)
    hex_zones = q.execute().data
    if not hex_zones:
        print("No hex zones found — run pipeline/seed_demo.py first (demo mode) "
              "or pipeline/generate_hex_grid.py --push (production).")
        return

    model_module.load_model()
    generated_at = utcnow()
    pred_rows = []
    danger_hexes = []

    for hz in hex_zones:
        static = hz.get("static_features") or {}
        recent_temp_c, recent_humidity_pct = latest_reading_for_hex(db, hz["hex_id"])
        for horizon in HORIZONS:
            result = model_module.predict(static, recent_temp_c, recent_humidity_pct, generated_at, horizon)
            hi = heat_index_c(result["pred_temp_c"], result["pred_humidity_pct"])
            band = risk_band_for(hi)
            row = {
                "hex_id": hz["hex_id"],
                "model_version": settings.MODEL_VERSION,
                "generated_at": generated_at.isoformat(),
                "horizon_hours": horizon,
                "valid_at": (generated_at + timedelta(hours=horizon)).isoformat(),
                "pred_temp_c": result["pred_temp_c"],
                "pred_temp_uncertainty_c": result["pred_temp_uncertainty_c"],
                "pred_humidity_pct": result["pred_humidity_pct"],
                "heat_index_c": hi,
                "risk_band": band.key,
            }
            pred_rows.append(row)
            if band.key in ALERT_TRIGGER_BANDS:
                danger_hexes.append(row)

    db.table("predictions").insert(pred_rows).execute()
    n_alerts = queue_alerts(db, danger_hexes)

    completed_at = utcnow()
    db.table("pipeline_runs").insert(
        {
            "job_type": "inference",
            "source": settings.MODEL_VERSION,
            "status": "success",
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "metrics": {
                "hex_zones_scored": len(hex_zones),
                "predictions_written": len(pred_rows),
                "danger_or_extreme_predictions": len(danger_hexes),
                "alerts_queued": n_alerts,
                "duration_seconds": (completed_at - started_at).total_seconds(),
            },
        }
    ).execute()

    print(
        f"Inference complete: {len(hex_zones)} hex zones x {len(HORIZONS)} horizons "
        f"= {len(pred_rows)} predictions written. {n_alerts} alerts queued."
    )


def queue_alerts(db, danger_rows) -> int:
    """F5 — Personalized Alerts. Any user whose home/work hex just crossed into
    danger/extreme at horizon 0 (i.e. right now) gets an alert row queued."""
    now_rows = [r for r in danger_rows if r["horizon_hours"] == 0]
    if not now_rows:
        return 0
    hex_to_row = {r["hex_id"]: r for r in now_rows}

    users = db.table("users").select("*").execute().data
    count = 0
    for u in users:
        for hex_field in ("home_hex_id", "work_hex_id"):
            hex_id = u.get(hex_field)
            if hex_id and hex_id in hex_to_row:
                row = hex_to_row[hex_id]
                lang = u.get("preferred_language", "en")
                message_en = f"Heat alert: your {hex_field.split('_')[0]} zone is at {row['risk_band'].upper()} risk (feels like {row['heat_index_c']}°C)."
                message = translate(message_en, lang)
                db.table("alerts").insert(
                    {
                        "user_id": u["id"],
                        "hex_id": hex_id,
                        "triggered_at": row["valid_at"],
                        "risk_band": row["risk_band"],
                        "delivered": False,
                        "channel": "push",
                        "message": message,
                    }
                ).execute()
                count += 1
    return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--city-id", default=None)
    args = parser.parse_args()
    run(city_id=args.city_id)
