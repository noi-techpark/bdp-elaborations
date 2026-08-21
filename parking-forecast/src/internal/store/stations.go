// SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>
//
// SPDX-License-Identifier: AGPL-3.0-or-later

package store

import "database/sql"

type Station struct {
	Scode       string
	Name        string
	StationType string
	Lat         float64
	Lon         float64
	Capacity    float64 // 0 if unknown
	Active      bool
}

// UpsertStations replaces the known station set. Stations no longer present
// upstream are marked inactive rather than deleted, so historical data/models
// stay addressable.
func (db *DB) UpsertStations(stations []Station) error {
	tx, err := db.sql.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()

	if _, err := tx.Exec(`UPDATE stations SET active = 0`); err != nil {
		return err
	}

	stmt, err := tx.Prepare(`
		INSERT INTO stations (scode, name, station_type, lat, lon, capacity, active)
		VALUES (?, ?, ?, ?, ?, ?, 1)
		ON CONFLICT(scode) DO UPDATE SET
			name = excluded.name,
			station_type = excluded.station_type,
			lat = excluded.lat,
			lon = excluded.lon,
			capacity = excluded.capacity,
			active = 1
	`)
	if err != nil {
		return err
	}
	defer stmt.Close()

	for _, s := range stations {
		if _, err := stmt.Exec(s.Scode, s.Name, s.StationType, s.Lat, s.Lon, s.Capacity); err != nil {
			return err
		}
	}

	return tx.Commit()
}

func (db *DB) ActiveStations() ([]Station, error) {
	rows, err := db.sql.Query(`
		SELECT scode, name, station_type, lat, lon, COALESCE(capacity, 0), active
		FROM stations WHERE active = 1 ORDER BY scode
	`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []Station
	for rows.Next() {
		var s Station
		if err := rows.Scan(&s.Scode, &s.Name, &s.StationType, &s.Lat, &s.Lon, &s.Capacity, &s.Active); err != nil {
			return nil, err
		}
		out = append(out, s)
	}
	return out, rows.Err()
}

func (db *DB) StationByCode(scode string) (Station, bool, error) {
	var s Station
	err := db.sql.QueryRow(`
		SELECT scode, name, station_type, lat, lon, COALESCE(capacity, 0), active
		FROM stations WHERE scode = ?
	`, scode).Scan(&s.Scode, &s.Name, &s.StationType, &s.Lat, &s.Lon, &s.Capacity, &s.Active)
	if err == sql.ErrNoRows {
		return Station{}, false, nil
	}
	if err != nil {
		return Station{}, false, err
	}
	return s, true, nil
}
