# SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from datetime import datetime, timedelta, timezone
from pathlib import Path

from forecasting import features, forest
from storage import db, occupancy, reference, stations
from predict.main import predict_station


def constant_forest(value: float):
    """Builds a forest that (approximately) always predicts value,
    regardless of input — enough to exercise predict_station's bookkeeping
    without depending on forest.fit's split-selection behavior.
    """
    x = [[0.0] * features.NUM_FEATURES for _ in range(20)]
    y = [value] * 20
    cfg = forest.Config(num_trees=3, min_leaf_samples=1)
    return forest.fit(x, y, cfg)


def _seed_history(conn, scode: str, capacity: float, cutoff: datetime):
    from_ts = cutoff - timedelta(days=8)
    points = []
    ts = from_ts
    while ts <= cutoff:
        points.append(occupancy.OccPoint(ts=ts, value=0.3 * capacity))
        ts += timedelta(seconds=features.STEP_SECONDS)
    occupancy.insert_occupancy(conn, scode, points)


def _holidays_and_weather(cutoff: datetime):
    holidays = {}
    weather = {}
    d = (cutoff - timedelta(days=10)).date()
    end = (cutoff + timedelta(days=3)).date()
    while d <= end:
        key = d.isoformat()
        holidays[key] = reference.DayInfo(is_school=True)
        weather[key] = 1
        d += timedelta(days=1)
    return holidays, weather


def test_predict_station_produces_full_horizon_and_handles_missing_model(tmp_path: Path):
    cutoff = datetime(2026, 1, 8, 12, 0, 0, tzinfo=timezone.utc)
    horizon_steps = 12  # 1 hour at 5-minute steps

    holidays, weather = _holidays_and_weather(cutoff)
    from_ts = cutoff - timedelta(days=8)

    conn = db.open_db(str(tmp_path / "test.db"))

    station_a = stations.Station(scode="A", name="", station_type="ParkingStation", lat=0, lon=0, capacity=100)
    station_c = stations.Station(scode="C", name="", station_type="ParkingStation", lat=0, lon=0, capacity=10)
    stations.upsert_stations(conn, [station_a, station_c])
    _seed_history(conn, "A", station_a.capacity, cutoff)

    fc_a = predict_station(conn, station_a, constant_forest(0.4), holidays, weather, from_ts, cutoff, horizon_steps, 0.1, 0.9)
    fc_c = predict_station(conn, station_c, None, holidays, weather, from_ts, cutoff, horizon_steps, 0.1, 0.9)  # no trained model

    assert len(fc_a.points) == horizon_steps
    assert len(fc_c.points) == horizon_steps

    for p in fc_a.points:
        assert p.mean is not None
        assert 0 <= p.mean <= 100
        assert p.lo is not None and p.hi is not None
        assert p.lo <= p.mean <= p.hi

    for p in fc_c.points:
        assert p.mean is None and p.lo is None and p.hi is None


def test_predict_station_horizons_are_independent(tmp_path: Path):
    """A direct-horizon model carries no state between steps: the forecast
    for the first hour must be identical whether or not later, longer
    horizons are also requested — a recursive rollout would fail this, since
    a longer requested horizon means more compounding by the time you reach
    any given step.
    """
    cutoff = datetime(2026, 1, 8, 12, 0, 0, tzinfo=timezone.utc)
    holidays, weather = _holidays_and_weather(cutoff)
    from_ts = cutoff - timedelta(days=8)

    conn = db.open_db(str(tmp_path / "test.db"))
    station = stations.Station(scode="A", name="", station_type="ParkingStation", lat=0, lon=0, capacity=100)
    stations.upsert_stations(conn, [station])
    _seed_history(conn, "A", station.capacity, cutoff)

    model = constant_forest(0.4)

    full = predict_station(conn, station, model, holidays, weather, from_ts, cutoff, 48, 0.1, 0.9)  # 4h at 5-min steps
    short = predict_station(conn, station, model, holidays, weather, from_ts, cutoff, 12, 0.1, 0.9)  # 1h at 5-min steps

    for i in range(len(short.points)):
        assert full.points[i].mean == short.points[i].mean
