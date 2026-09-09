# SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from forecasting import resultjson


def test_write_result_json_matches_documented_schema(tmp_path: Path):
    start = datetime(2026, 1, 8, 10, 5, 0, tzinfo=timezone.utc)
    lo, mean, hi = 10.4, 12.0, 13.6

    path = tmp_path / "result.json"
    resultjson.write_result_json(
        str(path),
        start,
        48,
        "2.0",
        [
            resultjson.StationForecast(
                scode="STATION1",
                points=[
                    resultjson.Point(ts=start, lo=lo, mean=mean, hi=hi),
                    resultjson.Point(ts=start + timedelta(minutes=5)),  # all-null point
                ],
            )
        ],
    )

    doc = json.loads(path.read_text())

    for key in (
        "publish_timestamp",
        "forecast_start_timestamp",
        "forecast_period_seconds",
        "forecast_duration_hours",
        "model_version",
        "schema_version",
        "timeseries",
    ):
        assert key in doc

    assert doc["forecast_start_timestamp"] == "2026-01-08 10:05:00+00:00"
    assert doc["forecast_period_seconds"] == 300

    points = doc["timeseries"]["STATION1"]
    assert len(points) == 2

    first = points[0]
    for key in ("ts", "lo", "mean", "hi", "rmse"):
        assert key in first
    assert first["lo"] == 10.4
    assert first["mean"] == 12.0
    assert first["hi"] == 13.6
    assert first["rmse"] is None

    second = points[1]
    assert second["lo"] is None
    assert second["mean"] is None
    assert second["hi"] is None
