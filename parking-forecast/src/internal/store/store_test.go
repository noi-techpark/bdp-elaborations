// SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>
//
// SPDX-License-Identifier: AGPL-3.0-or-later

package store

import (
	"path/filepath"
	"testing"
	"time"
)

func openTestDB(t *testing.T) *DB {
	t.Helper()
	db, err := Open(filepath.Join(t.TempDir(), "test.db"))
	if err != nil {
		t.Fatalf("opening test db: %v", err)
	}
	t.Cleanup(func() { db.Close() })
	return db
}

func TestStationsRoundTrip(t *testing.T) {
	db := openTestDB(t)

	stations := []Station{
		{Scode: "A", Name: "Station A", StationType: "ParkingStation", Lat: 46.5, Lon: 11.3, Capacity: 100},
		{Scode: "B", Name: "Station B", StationType: "ParkingSensor", Lat: 46.6, Lon: 11.4, Capacity: 1},
	}
	if err := db.UpsertStations(stations); err != nil {
		t.Fatalf("UpsertStations: %v", err)
	}

	got, err := db.ActiveStations()
	if err != nil {
		t.Fatalf("ActiveStations: %v", err)
	}
	if len(got) != 2 {
		t.Fatalf("got %d stations, want 2", len(got))
	}

	// re-upserting a subset should deactivate the station left out
	if err := db.UpsertStations([]Station{stations[0]}); err != nil {
		t.Fatalf("UpsertStations (subset): %v", err)
	}
	got, err = db.ActiveStations()
	if err != nil {
		t.Fatalf("ActiveStations: %v", err)
	}
	if len(got) != 1 || got[0].Scode != "A" {
		t.Fatalf("expected only station A to remain active, got %+v", got)
	}
}

func TestOccupancyIngestCursorAndLookup(t *testing.T) {
	db := openTestDB(t)

	if _, ok, err := db.LastOccupancyTS("A"); err != nil || ok {
		t.Fatalf("expected no cursor yet, got ok=%v err=%v", ok, err)
	}

	base := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	points := []OccPoint{
		{TS: base, Value: 10},
		{TS: base.Add(5 * time.Minute), Value: 12},
		{TS: base.Add(10 * time.Minute), Value: 14},
	}
	if err := db.InsertOccupancy("A", points); err != nil {
		t.Fatalf("InsertOccupancy: %v", err)
	}

	last, ok, err := db.LastOccupancyTS("A")
	if err != nil || !ok {
		t.Fatalf("LastOccupancyTS: ok=%v err=%v", ok, err)
	}
	if !last.Equal(base.Add(10 * time.Minute)) {
		t.Fatalf("last ts = %v, want %v", last, base.Add(10*time.Minute))
	}

	earliest, ok, err := db.EarliestOccupancyTS("A")
	if err != nil || !ok || !earliest.Equal(base) {
		t.Fatalf("EarliestOccupancyTS = %v, ok=%v err=%v", earliest, ok, err)
	}

	m, err := db.OccupancyMap("A", base, base.Add(10*time.Minute))
	if err != nil {
		t.Fatalf("OccupancyMap: %v", err)
	}
	if len(m) != 3 || m[base.Unix()] != 10 {
		t.Fatalf("OccupancyMap = %v", m)
	}

	// inserting further points should advance, never rewind, the cursor
	if err := db.InsertOccupancy("A", []OccPoint{{TS: base.Add(15 * time.Minute), Value: 16}}); err != nil {
		t.Fatalf("InsertOccupancy (2nd batch): %v", err)
	}
	last, _, _ = db.LastOccupancyTS("A")
	if !last.Equal(base.Add(15 * time.Minute)) {
		t.Fatalf("last ts after 2nd batch = %v", last)
	}
}

func TestPurgeOccupancyBefore(t *testing.T) {
	db := openTestDB(t)

	base := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	if err := db.InsertOccupancy("A", []OccPoint{
		{TS: base, Value: 1},
		{TS: base.Add(5 * time.Minute), Value: 2},
		{TS: base.Add(10 * time.Minute), Value: 3},
	}); err != nil {
		t.Fatalf("InsertOccupancy: %v", err)
	}

	cutoff := base.Add(6 * time.Minute)
	purged, err := db.PurgeOccupancyBefore(cutoff)
	if err != nil {
		t.Fatalf("PurgeOccupancyBefore: %v", err)
	}
	if purged != 2 {
		t.Fatalf("purged %d rows, want 2", purged)
	}

	m, err := db.OccupancyMap("A", base, base.Add(10*time.Minute))
	if err != nil {
		t.Fatalf("OccupancyMap: %v", err)
	}
	if len(m) != 1 {
		t.Fatalf("expected 1 remaining point after purge, got %d: %v", len(m), m)
	}
	if _, ok := m[base.Add(10*time.Minute).Unix()]; !ok {
		t.Fatalf("expected the newest point to survive the purge, got %v", m)
	}

	// the ingest cursor tracks the latest ingested ts, independent of
	// retention purging — it must not move backwards or disappear
	last, ok, err := db.LastOccupancyTS("A")
	if err != nil || !ok || !last.Equal(base.Add(10*time.Minute)) {
		t.Fatalf("LastOccupancyTS after purge = %v, ok=%v err=%v", last, ok, err)
	}
}

func TestHolidaysAndWeatherRoundTrip(t *testing.T) {
	db := openTestDB(t)

	if err := db.UpsertHolidays(map[string]DayInfo{
		"2026-01-01": {IsSchool: false, IsHoliday: true},
		"2026-01-02": {IsSchool: true, IsHoliday: false},
	}); err != nil {
		t.Fatalf("UpsertHolidays: %v", err)
	}
	holidays, err := db.AllHolidays()
	if err != nil {
		t.Fatalf("AllHolidays: %v", err)
	}
	if !holidays["2026-01-01"].IsHoliday || holidays["2026-01-02"].IsHoliday {
		t.Fatalf("unexpected holidays: %+v", holidays)
	}

	if date, err := db.LatestWeatherDate(); err != nil || date != "" {
		t.Fatalf("expected empty latest weather date initially, got %q err=%v", date, err)
	}
	if err := db.UpsertWeather(map[string]int{"2026-01-01": 3, "2026-01-03": 7}); err != nil {
		t.Fatalf("UpsertWeather: %v", err)
	}
	date, err := db.LatestWeatherDate()
	if err != nil || date != "2026-01-03" {
		t.Fatalf("LatestWeatherDate = %q, err=%v", date, err)
	}
	weather, err := db.AllWeather()
	if err != nil || weather["2026-01-01"] != 3 {
		t.Fatalf("AllWeather = %+v, err=%v", weather, err)
	}
}

func TestModelsRoundTrip(t *testing.T) {
	db := openTestDB(t)

	if _, _, ok, err := db.LoadModel("A"); err != nil || ok {
		t.Fatalf("expected no model yet, ok=%v err=%v", ok, err)
	}

	blob := []byte{1, 2, 3, 4}
	trainedAt := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	if err := db.SaveModel("A", blob, trainedAt, 1234); err != nil {
		t.Fatalf("SaveModel: %v", err)
	}

	got, gotTrainedAt, ok, err := db.LoadModel("A")
	if err != nil || !ok {
		t.Fatalf("LoadModel: ok=%v err=%v", ok, err)
	}
	if string(got) != string(blob) || !gotTrainedAt.Equal(trainedAt) {
		t.Fatalf("LoadModel roundtrip mismatch: %v %v", got, gotTrainedAt)
	}

	withModels, err := db.StationsWithModels()
	if err != nil || !withModels["A"] {
		t.Fatalf("StationsWithModels = %v, err=%v", withModels, err)
	}

	// re-saving should overwrite, not duplicate
	if err := db.SaveModel("A", []byte{9}, trainedAt.Add(time.Hour), 1); err != nil {
		t.Fatalf("SaveModel (overwrite): %v", err)
	}
	got, _, _, _ = db.LoadModel("A")
	if string(got) != string([]byte{9}) {
		t.Fatalf("expected overwritten blob, got %v", got)
	}
}
