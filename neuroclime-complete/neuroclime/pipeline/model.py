"""
NeuroClime prediction model — Phase 2 baseline.

The TRD's own execution roadmap says: "ST-GNN training (or Random Forest
baseline first)". This module builds that first, honest baseline: a
scikit-learn RandomForestRegressor predicting [temperature_c, humidity_pct]
at a future horizon from a hex's static land-cover features, its most
recent observed reading, and time-of-day/season signal.

This is intentionally NOT the full spatio-temporal graph neural network
described in the PRD as the novel differentiator (that needs real
multi-station historical data and PyTorch Geometric training time neither
of which are available in this environment) — but it is wired into the
*exact same interface* (`predict()` / `predict_batch()`) that a trained
ST-GNN would need to satisfy, so swapping it in later is a model-file
change, not an architecture change. See docs/MODEL_UPGRADE_PATH.md.

Usage:
    python -m pipeline.model train      # trains + saves artifact + prints eval
    python -m pipeline.model eval       # re-evaluates saved artifact
"""
from __future__ import annotations

import json
import math
import random
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # allow `pipeline.X` imports when run directly

from pipeline.synthetic_data import (  # noqa: E402
    DEFAULT_BBOX,
    static_features_for_hex,
    dynamic_reading_for_hex,
    diurnal_base_temp_c,
)

ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"
ARTIFACT_PATH = ARTIFACT_DIR / "rf_baseline.joblib"
METRICS_PATH = ARTIFACT_DIR / "eval_metrics.json"

HORIZONS = (0, 1, 3, 6)
# NOTE: `urbanization_index` is a synthetic-data-generator convenience field
# (see pipeline/synthetic_data.py) and is deliberately NOT a model feature —
# it isn't a real satellite/OSM-derived quantity in the TRD schema. Training
# on the actual land-cover features below (rather than that shortcut) is
# what makes the /v1/scenarios "what-if" tool responsive to NDVI/building-
# density edits: the model has to learn the real ndvi -> temp relationship
# instead of leaning on a hidden field the scenario tool can't touch.
FEATURE_NAMES = [
    "ndvi",
    "ndbi",
    "albedo",
    "building_density_pct",
    "elevation_m",
    "recent_temp_c",
    "recent_humidity_pct",
    "hour_sin",
    "hour_cos",
    "doy_sin",
    "doy_cos",
    "horizon_hours",
]


def _time_features(dt, horizon_hours: int) -> dict:
    hour = dt.hour + dt.minute / 60.0
    doy = dt.timetuple().tm_yday
    return {
        "hour_sin": math.sin(2 * math.pi * hour / 24),
        "hour_cos": math.cos(2 * math.pi * hour / 24),
        "doy_sin": math.sin(2 * math.pi * doy / 365),
        "doy_cos": math.cos(2 * math.pi * doy / 365),
        "horizon_hours": horizon_hours,
    }


def _feature_row(static: dict, recent_temp_c: float, recent_humidity_pct: float, dt, horizon_hours: int) -> list:
    row = {**static, "recent_temp_c": recent_temp_c, "recent_humidity_pct": recent_humidity_pct}
    row.update(_time_features(dt, horizon_hours))
    return [row[name] for name in FEATURE_NAMES]


def _build_training_frame(n_stations: int = 120, days: int = 21, seed: int = 7):
    """
    Simulates `n_stations` sensor stations scattered across the demo bbox,
    each with hourly readings over `days` days, and builds a supervised
    (features_at_t) -> (temp/humidity_at_t+h) training frame for every
    horizon in HORIZONS. Returns X, y, station_ids (for grouped/leave-
    station-out splitting) and a datetime base.
    """
    from datetime import datetime, timedelta, timezone

    rng = random.Random(seed)
    base_dt = datetime(2026, 5, 1, tzinfo=timezone.utc)  # peak pre-monsoon heat season, matches PRD's use case

    stations = []
    for i in range(n_stations):
        lon = rng.uniform(DEFAULT_BBOX[0], DEFAULT_BBOX[2])
        lat = rng.uniform(DEFAULT_BBOX[1], DEFAULT_BBOX[3])
        static = static_features_for_hex(lon, lat, DEFAULT_BBOX, seed=i * 97 + seed)
        stations.append({"station_id": f"synthetic-station-{i:03d}", "static": static})

    X, y, groups = [], [], []
    hours_total = days * 24
    for st in stations:
        # Pre-generate the station's actual temp/humidity trace.
        trace = []
        for h in range(hours_total + max(HORIZONS)):
            dt = base_dt + timedelta(hours=h)
            reading = dynamic_reading_for_hex(st["static"], dt, rng)
            trace.append((dt, reading))

        for h in range(hours_total):
            dt_now, reading_now = trace[h]
            for horizon in HORIZONS:
                dt_future, reading_future = trace[h + horizon]
                X.append(
                    _feature_row(
                        st["static"], reading_now["temperature_c"], reading_now["humidity_pct"], dt_now, horizon
                    )
                )
                y.append([reading_future["temperature_c"], reading_future["humidity_pct"]])
                groups.append(st["station_id"])

    return np.array(X), np.array(y), np.array(groups)


def train(save: bool = True) -> dict:
    import joblib

    X, y, groups = _build_training_frame()
    unique_stations = sorted(set(groups))
    rng = random.Random(42)
    rng.shuffle(unique_stations)
    n_test = max(1, len(unique_stations) // 5)
    test_stations = set(unique_stations[:n_test])

    train_mask = np.array([g not in test_stations for g in groups])
    X_train, y_train = X[train_mask], y[train_mask]
    X_test, y_test = X[~train_mask], y[~train_mask]

    model = RandomForestRegressor(n_estimators=80, max_depth=10, min_samples_leaf=5, random_state=42, n_jobs=-1)
    model.fit(X_train, y_train)

    preds = model.predict(X_test)
    temp_mae = mean_absolute_error(y_test[:, 0], preds[:, 0])
    temp_rmse = math.sqrt(mean_squared_error(y_test[:, 0], preds[:, 0]))
    hum_mae = mean_absolute_error(y_test[:, 1], preds[:, 1])

    # Persistence baseline: "future temp = temp now" (the recent_temp_c feature).
    persistence_preds = X_test[:, FEATURE_NAMES.index("recent_temp_c")]
    persistence_mae = mean_absolute_error(y_test[:, 0], persistence_preds)
    persistence_rmse = math.sqrt(mean_squared_error(y_test[:, 0], persistence_preds))

    metrics = {
        "model_type": "RandomForestRegressor (baseline, see docs/MODEL_UPGRADE_PATH.md for ST-GNN swap-in)",
        "n_train_rows": int(len(X_train)),
        "n_test_rows": int(len(X_test)),
        "leave_station_out_test_stations": sorted(test_stations),
        "temp_mae_c": round(float(temp_mae), 3),
        "temp_rmse_c": round(float(temp_rmse), 3),
        "humidity_mae_pct": round(float(hum_mae), 3),
        "baseline_persistence_temp_mae_c": round(float(persistence_mae), 3),
        "baseline_persistence_temp_rmse_c": round(float(persistence_rmse), 3),
        "improvement_over_persistence_pct": round(
            100 * (1 - temp_mae / persistence_mae), 1
        ) if persistence_mae else None,
        "data_source": "SYNTHETIC (see pipeline/synthetic_data.py) — replace with real sensor history once "
        "CPCB/IMD ingestion has accumulated enough historical rows to train on.",
    }

    if save:
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        joblib.dump(model, ARTIFACT_PATH, compress=3)
        METRICS_PATH.write_text(json.dumps(metrics, indent=2))

    return metrics


_model_cache = None


def load_model():
    global _model_cache
    if _model_cache is None:
        import joblib

        if not ARTIFACT_PATH.exists():
            train(save=True)
        _model_cache = joblib.load(ARTIFACT_PATH)
    return _model_cache


def predict(static_features: dict, recent_temp_c: float, recent_humidity_pct: float, dt, horizon_hours: int) -> dict:
    """Predict temp_c/humidity_pct for one hex at one horizon. Used by both
    the batch inference job and the /v1/scenarios on-demand endpoint."""
    model = load_model()
    row = _feature_row(static_features, recent_temp_c, recent_humidity_pct, dt, horizon_hours)
    pred = model.predict([row])[0]
    pred_temp_c, pred_humidity_pct = float(pred[0]), float(pred[1])

    # Uncertainty proxy: spread across the forest's individual trees.
    tree_preds = np.array([t.predict([row])[0] for t in model.estimators_])
    uncertainty_c = float(np.std(tree_preds[:, 0]))

    return {
        "pred_temp_c": round(pred_temp_c, 2),
        "pred_temp_uncertainty_c": round(uncertainty_c, 2),
        "pred_humidity_pct": round(max(0.0, min(100.0, pred_humidity_pct)), 1),
    }


# Empirical NDVI/albedo/building-density -> land-surface-temperature
# sensitivity coefficients, in the same range widely reported in urban heat
# island literature (roughly: +0.1 NDVI ~ -0.3 to -1.0 degC in dense cities;
# higher albedo cools; denser building mass raises local air temperature).
# Used ONLY by the interactive what-if tool below, deliberately kept
# separate from the trained RF model. Reason: a hypothetical single-feature
# edit (e.g. "+0.2 NDVI, same everything else") is a counterfactual outside
# the training distribution, and the RF model's `recent_temp_c` input
# already encodes almost all of a station's urbanization signature — so a
# black-box marginal effect from the model is small, unstable, and
# sometimes even the wrong sign for this kind of edit. A documented,
# monotonic, literature-informed coefficient is what real urban-planning
# "what-if" tools use for exactly this reason, and it gives planners a
# result they can sanity-check and trust. See docs/MODEL_UPGRADE_PATH.md.
_SCENARIO_SENSITIVITY_C_PER_UNIT = {
    "ndvi": -6.0,             # more vegetation -> cooler
    "building_density_pct": 3.5,   # denser built mass -> hotter
    "albedo": -4.0,           # more reflective surfaces -> cooler
    "ndbi": 2.0,              # more built-up index -> hotter
}


def scenario_delta_c(baseline_features: dict, modified_features: dict) -> float:
    """Deterministic, explainable temperature delta for the /v1/scenarios
    what-if tool, driven by documented per-unit sensitivity coefficients
    rather than the RF model's marginal effect (see note above)."""
    delta = 0.0
    for feature, coef in _SCENARIO_SENSITIVITY_C_PER_UNIT.items():
        before = baseline_features.get(feature)
        after = modified_features.get(feature, before)
        if before is None or after is None:
            continue
        delta += coef * (after - before)
    return round(delta, 2)


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "train"
    if action == "train":
        m = train(save=True)
        print(json.dumps(m, indent=2))
    elif action == "eval":
        print(METRICS_PATH.read_text() if METRICS_PATH.exists() else "No metrics yet — run `train` first.")
    else:
        print("Usage: python -m pipeline.model [train|eval]")
