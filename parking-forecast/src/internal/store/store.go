// SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>
//
// SPDX-License-Identifier: AGPL-3.0-or-later

// Package store persists everything the parking forecast jobs need between
// runs in a single SQLite file (same convention as pollution_v2's
// checkpoint_cache.db): the incrementally-ingested occupancy history,
// holiday/weather reference data, station metadata and the fitted
// per-station forests. This replaces the old data-raw/*.csv,
// data-holidays/holidays.csv, data-meteo/meteo.csv and data-models/dnn_model*
// files.
package store

import (
	"database/sql"
	"fmt"
	"os"
	"path/filepath"

	_ "modernc.org/sqlite"
)

type DB struct {
	sql *sql.DB
}

const schema = `
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
-- to stay cheap as history and station count grow — see PurgeOccupancyBefore.
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
`

// Open opens (creating if needed) the SQLite cache at path and applies the schema.
func Open(path string) (*DB, error) {
	if dir := filepath.Dir(path); dir != "." {
		if err := os.MkdirAll(dir, 0o755); err != nil {
			return nil, fmt.Errorf("creating db directory: %w", err)
		}
	}

	sqlDB, err := sql.Open("sqlite", path)
	if err != nil {
		return nil, fmt.Errorf("opening sqlite db: %w", err)
	}
	// SQLite handles one writer at a time regardless; forcing a single
	// connection avoids SQLITE_BUSY churn under the concurrent per-station
	// goroutines ingest/train/predict use, at negligible cost given how
	// small and infrequent each query is.
	sqlDB.SetMaxOpenConns(1)

	for _, pragma := range []string{
		"PRAGMA journal_mode=WAL",
		"PRAGMA busy_timeout=10000",
		"PRAGMA foreign_keys=ON",
	} {
		if _, err := sqlDB.Exec(pragma); err != nil {
			return nil, fmt.Errorf("applying %q: %w", pragma, err)
		}
	}

	if _, err := sqlDB.Exec(schema); err != nil {
		return nil, fmt.Errorf("applying schema: %w", err)
	}

	return &DB{sql: sqlDB}, nil
}

func (db *DB) Close() error {
	return db.sql.Close()
}
