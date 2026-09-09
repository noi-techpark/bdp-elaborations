# SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from datetime import datetime, timedelta, timezone
from pathlib import Path

from storage import db, models, occupancy, reference, stations


def open_test_db(tmp_path: Path):
    return db.open_db(str(tmp_path / "test.db"))


def test_stations_round_trip(tmp_path: Path):
    conn = open_test_db(tmp_path)

    station_list = [
        stations.Station(scode="A", name="Station A", station_type="ParkingStation", lat=46.5, lon=11.3, capacity=100),
        stations.Station(scode="B", name="Station B", station_type="ParkingSensor", lat=46.6, lon=11.4, capacity=1),
    ]
    stations.upsert_stations(conn, station_list)

    got = stations.active_stations(conn)
    assert len(got) == 2

    # re-upserting a subset should deactivate the station left out
    stations.upsert_stations(conn, [station_list[0]])
    got = stations.active_stations(conn)
    assert len(got) == 1
    assert got[0].scode == "A"


def test_occupancy_ingest_cursor_and_lookup(tmp_path: Path):
    conn = open_test_db(tmp_path)

    assert occupancy.last_occupancy_ts(conn, "A") is None

    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    points = [
        occupancy.OccPoint(ts=base, value=10),
        occupancy.OccPoint(ts=base + timedelta(minutes=5), value=12),
        occupancy.OccPoint(ts=base + timedelta(minutes=10), value=14),
    ]
    occupancy.insert_occupancy(conn, "A", points)

    last = occupancy.last_occupancy_ts(conn, "A")
    assert last == base + timedelta(minutes=10)

    earliest = occupancy.earliest_occupancy_ts(conn, "A")
    assert earliest == base

    m = occupancy.occupancy_map(conn, "A", base, base + timedelta(minutes=10))
    assert len(m) == 3
    assert m[int(base.timestamp())] == 10

    # inserting further points should advance, never rewind, the cursor
    occupancy.insert_occupancy(conn, "A", [occupancy.OccPoint(ts=base + timedelta(minutes=15), value=16)])
    last = occupancy.last_occupancy_ts(conn, "A")
    assert last == base + timedelta(minutes=15)


def test_purge_occupancy_before(tmp_path: Path):
    conn = open_test_db(tmp_path)

    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    occupancy.insert_occupancy(
        conn,
        "A",
        [
            occupancy.OccPoint(ts=base, value=1),
            occupancy.OccPoint(ts=base + timedelta(minutes=5), value=2),
            occupancy.OccPoint(ts=base + timedelta(minutes=10), value=3),
        ],
    )

    cutoff = base + timedelta(minutes=6)
    purged = occupancy.purge_occupancy_before(conn, cutoff)
    assert purged == 2

    m = occupancy.occupancy_map(conn, "A", base, base + timedelta(minutes=10))
    assert len(m) == 1
    assert int((base + timedelta(minutes=10)).timestamp()) in m

    # the ingest cursor tracks the latest ingested ts, independent of
    # retention purging — it must not move backwards or disappear
    last = occupancy.last_occupancy_ts(conn, "A")
    assert last == base + timedelta(minutes=10)


def test_holidays_and_weather_round_trip(tmp_path: Path):
    conn = open_test_db(tmp_path)

    reference.upsert_holidays(
        conn,
        {
            "2026-01-01": reference.DayInfo(is_school=False, is_holiday=True),
            "2026-01-02": reference.DayInfo(is_school=True, is_holiday=False),
        },
    )
    holidays = reference.all_holidays(conn)
    assert holidays["2026-01-01"].is_holiday
    assert not holidays["2026-01-02"].is_holiday

    assert reference.latest_weather_date(conn) == ""
    reference.upsert_weather(conn, {"2026-01-01": 3, "2026-01-03": 7})
    assert reference.latest_weather_date(conn) == "2026-01-03"
    weather = reference.all_weather(conn)
    assert weather["2026-01-01"] == 3


def test_models_round_trip(tmp_path: Path):
    conn = open_test_db(tmp_path)

    assert models.load_model(conn, "A") is None

    blob = bytes([1, 2, 3, 4])
    trained_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    models.save_model(conn, "A", blob, trained_at, 1234)

    loaded = models.load_model(conn, "A")
    assert loaded is not None
    got_blob, got_trained_at = loaded
    assert got_blob == blob
    assert got_trained_at == trained_at

    with_models = models.stations_with_models(conn)
    assert "A" in with_models

    # re-saving should overwrite, not duplicate
    models.save_model(conn, "A", bytes([9]), trained_at + timedelta(hours=1), 1)
    got_blob, _ = models.load_model(conn, "A")
    assert got_blob == bytes([9])
