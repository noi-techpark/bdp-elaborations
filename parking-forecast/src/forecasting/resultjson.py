# SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Renders a batch of per-station forecasts as the legacy result.json file
documented in readme-for-data-consumers.md.

Publishing forecasts as native ODH/BDP time series is planned but not
implemented yet.
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Point:
    """occupancy-count units, clipped to [0, capacity]. None renders as JSON
    null (station not yet forecastable).
    """

    ts: datetime
    lo: float | None = None
    mean: float | None = None
    hi: float | None = None


@dataclass
class StationForecast:
    scode: str
    points: list[Point] = field(default_factory=list)


def _fmt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") + "+00:00"


def _fmt_with_micros(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f") + "+00:00"


def _round1(v: float | None) -> float | None:
    if v is None:
        return None
    return round(v, 1)


def write_result_json(
    path: str,
    forecast_start: datetime,
    hours_to_predict: int,
    model_version: str,
    forecasts: list[StationForecast],
) -> None:
    """Legacy schema_version "1.1"."""
    timeseries: dict[str, list[dict]] = {}
    for sf in forecasts:
        timeseries[sf.scode] = [
            {
                "ts": _fmt(p.ts),
                "lo": _round1(p.lo),
                "mean": _round1(p.mean),
                "hi": _round1(p.hi),
                "rmse": None,  # disabled upstream; kept in the schema for consumers
            }
            for p in sf.points
        ]

    doc = {
        "publish_timestamp": _fmt_with_micros(datetime.now(timezone.utc)),
        "forecast_start_timestamp": _fmt(forecast_start),
        "forecast_period_seconds": 300,
        "forecast_duration_hours": hours_to_predict,
        "model_version": model_version,
        "schema_version": "1.1",
        "timeseries": timeseries,
    }

    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    with open(path, "w") as f:
        json.dump(doc, f)
