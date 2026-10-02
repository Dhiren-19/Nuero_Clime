# Model upgrade path: RandomForest baseline → ST-GNN

## What's here now

`pipeline/model.py` trains a `RandomForestRegressor` that predicts
`[temperature_c, humidity_pct]` at a future horizon from:
- a hex's static land-cover features (NDVI, NDBI, albedo, building density, elevation)
- its most recent observed reading
- time-of-day / day-of-year signal (as sin/cos pairs)
- the requested forecast horizon (0, 1, 3, or 6 hours)

This matches the TRD's own Phase 2 instruction: *"ST-GNN training (or Random
Forest baseline first)"*. It was trained and evaluated here on synthetic
data (leave-station-out split) because no real historical sensor archive is
available in this environment — see `pipeline/synthetic_data.py`.

## Why not the full ST-GNN in this handoff

The PRD's core differentiator is a Spatio-Temporal Graph Neural Network
(PyTorch Geometric) that also models how heat propagates *between*
neighboring hexes (concrete radiating heat toward a park border, etc.),
learned from real multi-station historical time series. Building that here
would mean training it on the same synthetic generator, which would only
teach it to reconstruct the synthetic generator's own rules — not real
urban physics. That's not a useful artifact to hand off. A real ST-GNN needs
weeks-to-months of actual CPCB/IMD/satellite history to train on.

## What would need to change to swap it in

The integration surface is deliberately narrow, so this is a model-file
change, not an architecture change:

1. Build a graph where nodes = hex zones, edges = spatial adjacency
   (`h3.grid_ring`) weighted by e.g. inverse distance or shared building/NDVI
   similarity — `pipeline/coolest_route.py` already builds an analogous
   adjacency graph and can be reused as a starting point.
2. Train a PyTorch Geometric model (e.g. a temporal graph conv net) on real
   historical `sensor_readings` + `satellite_features` once enough history
   has accumulated (the TRD suggests waiting for several weeks of ingestion).
3. Replace the body of `pipeline.model.predict()` with a call into the
   trained GNN, keeping the same function signature:
   `predict(static_features, recent_temp_c, recent_humidity_pct, dt, horizon_hours) -> dict`.
   Every caller (`run_inference.py`, `scenarios.py`) is unaffected.
4. Re-point `pipeline.model.load_model()` at the new artifact format (GNN
   checkpoints instead of a `.joblib` file).

## Note on the what-if scenario tool specifically

`pipeline/model.scenario_delta_c()` deliberately does **not** call the
trained model for the what-if tool's temperature delta. A single-feature
counterfactual (e.g. "same everything, but +0.3 NDVI") sits outside what
either the RF baseline or a GNN trained on real conditions can answer
reliably, because in real data NDVI is entangled with a dozen other
correlated variables (building age, road width, tree canopy height...) that
a hypothetical edit doesn't touch. Real urban-planning "what-if" tools
generally use documented literature coefficients for exactly this reason —
see the comment above `_SCENARIO_SENSITIVITY_C_PER_UNIT` in `model.py` for
the values used and their rough empirical basis. This choice should hold
even after a GNN upgrade, for the same reason.
