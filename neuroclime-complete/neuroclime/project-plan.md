# NeuroClime — Prototype Project Plan

*Know your street's heat, not just your city's.*

Goal: a working end-to-end prototype (one city, core flows) — not the full 36-hour hackathon build. Scope has been trimmed accordingly; see "Cut for prototype" at the bottom.

---

## Phase 0 — Foundations
- [x] Repo structure created (`infra/`, `backend/`, `pipeline/`, `frontend/`)
- [x] Postgres/PostGIS schema written (`infra/schema.sql`) — all tables + RLS policies from TRD 2.2
- [ ] Supabase project created, `schema.sql` applied
- [ ] Pick pilot city + insert its row into `cities` (name, bbox)
- [ ] Supabase Auth configured (email/OTP for citizens, invite flow for authority)

## Phase 1 — Data pipeline
- [x] Hex grid generator written and tested (`pipeline/generate_hex_grid.py`) — 5,135 hexes generated for Pune's bbox at H3 res 9
- [ ] Run hex grid generator against real pilot-city `city_id`, push to Supabase
- [ ] Spatial join: assign each hex to a `ward_id` (point-in-polygon against `wards`)
- [ ] CPCB hourly pull → `sensor_readings` (start with historical CSV dump if API access is slow to get)
- [ ] IMD hourly pull → `sensor_readings`
- [ ] Sentinel-2 (Google Earth Engine) one-time batch → NDVI/NDBI/albedo into `hex_zones.static_features`
- [ ] ERA5-Land pull → `satellite_features`
- [ ] *(Deferred)* INSAT-3D/MOSDAC, MODIS MOD11A1

## Phase 2 — Model
- [ ] Build training feature table (join static + sensor + satellite features by hex/time)
- [ ] Train Random Forest / XGBoost baseline for temp + humidity at horizons 0/1/3/6h
- [ ] Leave-station-out evaluation → MAE/RMSE vs. baseline
- [ ] Derive heat index (WBGT-lite) + risk band bucketing (safe/caution/danger/extreme)
- [ ] *(Stretch)* Swap in ST-GNN (PyTorch Geometric, H3 adjacency graph) behind the same interface

## Phase 3 — Inference + API
- [x] FastAPI skeleton written and verified importable, all TRD 2.3.2 endpoints routed
- [ ] Scheduled inference job (cron/GitHub Actions, 15-min cycle) writing to `predictions`
- [ ] Wire `db.py` to a real Supabase project (currently placeholder env vars)
- [ ] Replace `/v1/scenarios` placeholder heuristic with real single-hex re-inference call
- [ ] `pipeline_runs` logging wired into ingestion + inference jobs (for admin dashboard)

## Phase 4 — Frontend
- [ ] MapLibre GL hex map, colored by risk band (colorblind-safe palette: color + icon + text)
- [ ] Time slider (now / +1h / +3h / +6h)
- [ ] Zone detail panel (temp, humidity, heat index, uncertainty)
- [ ] Ward ranking dashboard (authority view, role-gated)
- [ ] Scenario tool UI: adjust tree-cover %, show predicted delta
- [ ] Citizen auth flow (OTP) + authority auth flow (invite-based)

## Phase 5 — Polish & demo
- [ ] Admin pipeline status page (reads `pipeline_runs`)
- [ ] CSV report export (skip PDF for prototype)
- [ ] One hardcoded alt-language string set (mock Bhashini, not full integration)
- [ ] End-to-end demo script: citizen flow → authority flow → scenario tool, on real pilot-city data

---

## Cut for prototype (revisit post-prototype)
- Coolest Route Planner (P2)
- Offline ONNX on-device fallback
- Multilingual voice alerts (Bhashini TTS)
- PDF report generation (CSV only for now)
- Full Bhashini API integration (mocked with static strings)
- INSAT-3D and MODIS ingestion sources

## Artifacts produced so far
- `infra/schema.sql` — full schema + RLS, ready to apply to Supabase
- `pipeline/generate_hex_grid.py` — tested against Pune bbox (5,135 hexes)
- `backend/app/` — FastAPI skeleton, all routes stubbed against real Supabase queries
- `README.md` — setup instructions
