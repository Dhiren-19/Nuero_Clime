# NeuroClime — Hyperlocal Urban Microclimate Intelligence Platform

A working end-to-end prototype: data pipeline, ML baseline model, FastAPI
backend, and a web frontend, runnable with **zero cloud accounts** thanks to
a local demo-data mode — see [`NON_TECHNICAL_OVERVIEW.md`](./NON_TECHNICAL_OVERVIEW.md)
for a plain-language tour of what it does, and [`docs/MODEL_UPGRADE_PATH.md`](./docs/MODEL_UPGRADE_PATH.md)
for how the baseline model relates to the ST-GNN described in the PRD.

## Quick start (demo mode — no API keys needed)

```bash
# 1. Install dependencies
pip install -r requirements.txt --break-system-packages   # or use a venv

# 2. Seed a demo city (Pune bbox), synthetic sensor history, and hex grid
python -m pipeline.seed_demo

# 3. Train the baseline model (fast, ~seconds; auto-runs on first use anyway)
python -m pipeline.model train

# 4. Run the batch inference job to populate predictions
python -m pipeline.run_inference --city-id demo-city-pune

# 5. Start the backend
cd backend && uvicorn app.main:app --reload --port 8000

# 6. In another terminal, serve the frontend
cd frontend && python -m http.server 5500
```

Then open `http://localhost:5500` in a browser. Use the role switcher
(Citizen / Authority / Admin) at the top to see each user type's tools.
API docs are at `http://localhost:8000/docs`.

## Going to production: switching on real data

Everything above runs on synthetic-but-physically-plausible data (see
`pipeline/synthetic_data.py`) because CPCB, IMD, MOSDAC, NASA Earthdata,
Copernicus CDS, Google Earth Engine, and Bhashini all require registered
accounts this environment doesn't have. To switch to a real deployment:

1. Fill in the real keys in `.env` (see the comments in that file for what
   each one is and where to get it).
2. Set `DEMO_MODE=false`.
3. Create a Supabase project, run `infra/schema.sql` against it, and fill in
   `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` / `SUPABASE_JWT_SECRET`.
4. Replace `pipeline/seed_demo.py`'s synthetic readings with real ingestion —
   `pipeline/synthetic_data.py`'s output shape is exactly what
   `pipeline/model.py` and `pipeline/run_inference.py` expect, so a real
   ingestion script just needs to produce the same shape of rows.
5. Schedule `pipeline/run_inference.py` to run every `INFERENCE_REFRESH_MINUTES`
   (cron, GitHub Actions, etc.) — see TRD 2.4.

No other code changes are needed: `app/db.py` automatically switches from
the local JSON store to the real Supabase client the moment real credentials
are present.

## Structure
```
neuroclime/
├── .env                          # All API keys/URLs — see inline comments
├── NON_TECHNICAL_OVERVIEW.md     # Plain-language explanation of the product
├── infra/
│   └── schema.sql                # Full Postgres/PostGIS schema + RLS
├── pipeline/
│   ├── generate_hex_grid.py      # H3 hex grid generator (WKT + GeoJSON)
│   ├── synthetic_data.py         # Physically-plausible demo data generator
│   ├── seed_demo.py              # One-shot demo city/ward/hex/sensor seeder
│   ├── model.py                  # Baseline RandomForest model, train/predict
│   ├── heat_index.py             # Heat index + risk band derivation
│   ├── run_inference.py          # Batch job: predictions + alerts + logging
│   ├── coolest_route.py          # H3-graph shortest-heat-exposure routing
│   ├── bhashini.py               # Translation gateway + fallback dictionary
│   └── artifacts/                # Trained model + eval metrics (generated)
├── backend/
│   ├── app/
│   │   ├── main.py               # FastAPI app entrypoint
│   │   ├── config.py             # Centralized .env settings
│   │   ├── db.py                 # Real Supabase client OR local demo store
│   │   ├── local_db.py           # JSON-backed Supabase-query-builder mimic
│   │   ├── auth.py               # JWT (prod) / X-Demo-Role header (demo)
│   │   └── routers/              # hexzones, predictions, wards, scenarios,
│   │                              # reports, alerts, routes, internal
│   └── requirements.txt
└── frontend/
    ├── index.html / styles.css / app.js / i18n.js / config.js
    └── (map, time slider, ward ranking, what-if tool, alerts, coolest
        route, admin dashboard, EN/HI/MR language switcher)
```

## What's implemented
| Component | Status |
|---|---|
| Schema + RLS | Complete, matches TRD 2.2 |
| Hex grid generator | Complete (WKT for Supabase import, GeoJSON for the demo store/frontend) |
| Demo-mode local data store | Complete — full app runs with no cloud account |
| Synthetic data generator | Complete — models real urban-heat-island physics |
| Baseline ML model (RF) | Complete — trained, evaluated (leave-station-out, ~85% MAE improvement over persistence) |
| Batch inference job | Complete — predictions, heat index, risk bands, alert queueing |
| FastAPI routes | Complete and real — hexzones, predictions, wards, scenarios, reports, alerts, coolest route, admin |
| What-if scenario tool | Complete — literature-informed sensitivity coefficients (see `docs/MODEL_UPGRADE_PATH.md`) |
| Coolest route planner | Complete — H3-graph Dijkstra over live heat index |
| CSV report export | Complete |
| Multilingual (EN/HI/MR) | Complete for UI + alerts, via fallback dictionary; real Bhashini API wired but untested (no account) |
| Frontend web app | Complete — citizen/authority/admin views |
| Ingestion from real CPCB/IMD/ERA5/Sentinel-2/Bhashini | Not connected — needs registered API credentials (see .env) |
| ST-GNN model | Not built — baseline RF is the swap-in point, see `docs/MODEL_UPGRADE_PATH.md` |
| Offline-first ONNX edge model | Not built — noted as a next step |
| Mobile app | Not built — web app only |
