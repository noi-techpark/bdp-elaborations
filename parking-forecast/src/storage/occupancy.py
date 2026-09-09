# SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class OccPoint:
    ts: datetime
    value: float


def _to_unix(dt: datetime) -> int:
    return int(dt.timestamp())


def _from_unix(unix: int) -> datetime:
    return datetime.fromtimestamp(unix, tz=timezone.utc)


def last_occupancy_ts(conn: sqlite3.Connection, scode: str) -> datetime | None:
    row = conn.execute("SELECT last_ts FROM ingest_cursor WHERE scode = ?", (scode,)).fetchone()
    if row is None:
        return None
    return _from_unix(row[0])


def insert_occupancy(conn: sqlite3.Connection, scode: str, points: list[OccPoint]) -> None:
    """Advances the station's ingest cursor to the latest point, in the same
    transaction.
    """
    if not points:
        return

    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO occupancy (scode, ts, value) VALUES (?, ?, ?)",
            [(scode, _to_unix(p.ts), p.value) for p in points],
        )
        last = max(p.ts for p in points)
        conn.execute(
            """
            INSERT INTO ingest_cursor (scode, last_ts) VALUES (?, ?)
            ON CONFLICT(scode) DO UPDATE SET last_ts = excluded.last_ts
            """,
            (scode, _to_unix(last)),
        )


def occupancy_map(conn: sqlite3.Connection, scode: str, from_ts: datetime, to_ts: datetime) -> dict[int, float]:
    """Keyed by unix timestamp, for O(1) lag lookups while building feature
    rows.
    """
    rows = conn.execute(
        "SELECT ts, value FROM occupancy WHERE scode = ? AND ts BETWEEN ? AND ?",
        (scode, _to_unix(from_ts), _to_unix(to_ts)),
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def purge_occupancy_before(conn: sqlite3.Connection, cutoff: datetime) -> int:
    """Returns the number of rows removed."""
    with conn:
        cur = conn.execute("DELETE FROM occupancy WHERE ts < ?", (_to_unix(cutoff),))
        return cur.rowcount


def earliest_occupancy_ts(conn: sqlite3.Connection, scode: str) -> datetime | None:
    row = conn.execute("SELECT MIN(ts) FROM occupancy WHERE scode = ?", (scode,)).fetchone()
    if row is None or row[0] is None:
        return None
    return _from_unix(row[0])
