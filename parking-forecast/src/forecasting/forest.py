# SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Thin wrapper around scikit-learn's RandomForestRegressor for per-station
occupancy prediction. Evaluating each tree separately gives a natural
prediction interval (the spread across trees) — see predict_stats.
"""

import io
from dataclasses import dataclass

import joblib
import numpy as np
from sklearn.ensemble import RandomForestRegressor


@dataclass
class Config:
    num_trees: int = 60
    max_depth: int = 8
    min_leaf_samples: int = 20
    row_subsample: float = 0.8
    # smaller decorrelates trees ("mtry"), widening predict_stats's interval
    feature_subsample: float = 0.7
    seed: int = 1


def fit(x: list[list[float]], y: list[float], cfg: Config) -> RandomForestRegressor:
    model = RandomForestRegressor(
        n_estimators=cfg.num_trees,
        max_depth=cfg.max_depth,
        min_samples_leaf=cfg.min_leaf_samples,
        max_samples=cfg.row_subsample,
        max_features=cfg.feature_subsample,
        random_state=cfg.seed,
        n_jobs=-1,
    )
    model.fit(x, y)
    return model


def predict_all(model: RandomForestRegressor, x: list[float]) -> np.ndarray:
    """One prediction per tree in the forest."""
    row = np.asarray(x, dtype=float).reshape(1, -1)
    return np.array([tree.predict(row)[0] for tree in model.estimators_])


def predict_stats(model: RandomForestRegressor, x: list[float], lo_pct: float, hi_pct: float) -> tuple[float, float, float]:
    """mean/lo/hi across the forest's trees, lo/hi being the lo_pct/hi_pct
    percentiles of the individual trees' predictions.
    """
    preds = predict_all(model, x)
    mean = float(preds.mean())
    lo = float(np.percentile(preds, lo_pct * 100))
    hi = float(np.percentile(preds, hi_pct * 100))
    return mean, lo, hi


def marshal(model: RandomForestRegressor) -> bytes:
    buf = io.BytesIO()
    joblib.dump(model, buf)
    return buf.getvalue()


def unmarshal(blob: bytes) -> RandomForestRegressor:
    return joblib.load(io.BytesIO(blob))
