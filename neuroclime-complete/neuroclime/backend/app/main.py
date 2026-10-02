"""
NeuroClime — FastAPI inference & data service.

This is the read-heavy public API described in TRD 2.3.2. It serves
pre-computed predictions from the `predictions` cache table — no live
model inference in the request path, except /v1/scenarios.

Run locally:
    uvicorn app.main:app --reload --port 8000
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db import is_demo_mode
from app.routers import hexzones, predictions, wards, scenarios, reports, internal, alerts, routes

app = FastAPI(
    title="NeuroClime API",
    version="0.2.0",
    description="Hyperlocal urban microclimate intelligence — inference & data API",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(hexzones.router, prefix="/v1/hexzones", tags=["hexzones"])
app.include_router(predictions.router, prefix="/v1/predictions", tags=["predictions"])
app.include_router(wards.router, prefix="/v1/wards", tags=["wards"])
app.include_router(scenarios.router, prefix="/v1/scenarios", tags=["scenarios"])
app.include_router(reports.router, prefix="/v1/reports", tags=["reports"])
app.include_router(alerts.router, prefix="/v1/alerts", tags=["alerts"])
app.include_router(routes.router, prefix="/v1/routes/coolest", tags=["routes"])
app.include_router(internal.router, prefix="/internal/pipeline", tags=["admin"])

# Locally-generated CSV reports are served from here in demo mode; in
# production these live in a Supabase Storage bucket instead (see
# app/routers/reports.py).
settings.LOCAL_DATA_DIR.joinpath("reports").mkdir(parents=True, exist_ok=True)
app.mount("/reports", StaticFiles(directory=str(settings.LOCAL_DATA_DIR / "reports")), name="reports")


@app.get("/healthz")
def healthz():
    return {"status": "ok", "demo_mode": is_demo_mode(), "model_version": settings.MODEL_VERSION}
