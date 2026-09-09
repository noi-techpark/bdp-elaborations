# SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import sqlite3
from dataclasses import dataclass


@dataclass
class Station:
    scode: str
    name: str
    station_type: str
    lat: float
    lon: float
    capacity: float = 0.0  # 0 if unknown
    active: bool = True


def upsert_stations(conn: sqlite3.Connection, stations: list[Station]) -> None:
    """Stations no longer present upstream are marked inactive rather than
    deleted, so historical data/models stay addressable.
    """
    with conn:
        conn.execute("UPDATE stations SET active = 0")
        conn.executemany(
            """
            INSERT INTO stations (scode, name, station_type, lat, lon, capacity, active)
            VALUES (?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(scode) DO UPDATE SET
                name = excluded.name,
                station_type = excluded.station_type,
                lat = excluded.lat,
                lon = excluded.lon,
                capacity = excluded.capacity,
                active = 1
            """,
            [(s.scode, s.name, s.station_type, s.lat, s.lon, s.capacity) for s in stations],
        )


def active_stations(conn: sqlite3.Connection) -> list[Station]:
    rows = conn.execute(
        """
        SELECT scode, name, station_type, lat, lon, COALESCE(capacity, 0), active
        FROM stations WHERE active = 1 ORDER BY scode
        """
    ).fetchall()
    return [Station(scode=r[0], name=r[1], station_type=r[2], lat=r[3], lon=r[4], capacity=r[5], active=bool(r[6])) for r in rows]


def station_by_code(conn: sqlite3.Connection, scode: str) -> Station | None:
    row = conn.execute(
        """
        SELECT scode, name, station_type, lat, lon, COALESCE(capacity, 0), active
        FROM stations WHERE scode = ?
        """,
        (scode,),
    ).fetchone()
    if row is None:
        return None
    return Station(scode=row[0], name=row[1], station_type=row[2], lat=row[3], lon=row[4], capacity=row[5], active=bool(row[6]))
