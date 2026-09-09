# SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Persists everything the parking forecast jobs need between runs in a
single SQLite file: occupancy history, holiday/weather reference data,
station metadata and the fitted per-station forests.
"""

import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS stations (
    scode        TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    station_type TEXT NOT NULL,
    lat          REAL NOT NULL,
    lon          REAL NOT NULL,
    capacity     REAL,
    active       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS occupancy (
    scode TEXT NOT NULL,
    ts    INTEGER NOT NULL, -- unix seconds, UTC
    value REAL NOT NULL,
    PRIMARY KEY (scode, ts)
) WITHOUT ROWID;

-- (scode, ts) above doesn't help "WHERE ts < ?" across every station (ts
-- isn't the leading column), which is exactly what retention purging needs
-- to stay cheap as history and station count grow — see purge_occupancy_before.
CREATE INDEX IF NOT EXISTS idx_occupancy_ts ON occupancy (ts);

CREATE TABLE IF NOT EXISTS ingest_cursor (
    scode   TEXT PRIMARY KEY,
    last_ts INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS holidays (
    date       TEXT PRIMARY KEY, -- ISO date, YYYY-MM-DD
    is_school  INTEGER NOT NULL,
    is_holiday INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS weather (
    date         TEXT PRIMARY KEY, -- ISO date, YYYY-MM-DD
    symbol_value INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS models (
    scode       TEXT PRIMARY KEY,
    trained_at  INTEGER NOT NULL,
    train_rows  INTEGER NOT NULL,
    forest_blob BLOB NOT NULL
);
"""


def open_db(path: str) -> sqlite3.Connection:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    conn = sqlite3.connect(path, check_same_thread=False)
    for pragma in ("PRAGMA journal_mode=WAL", "PRAGMA busy_timeout=10000", "PRAGMA foreign_keys=ON"):
        conn.execute(pragma)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn
