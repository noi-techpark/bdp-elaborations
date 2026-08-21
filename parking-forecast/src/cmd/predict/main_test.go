// SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>
//
// SPDX-License-Identifier: AGPL-3.0-or-later

package main

import (
	"testing"
	"time"

	"parking-forecast/internal/config"
	"parking-forecast/internal/features"
	"parking-forecast/internal/forest"
	"parking-forecast/internal/store"
)

// constantForest builds a forest that (approximately) always predicts value,
// regardless of input — enough to exercise predictStation's bookkeeping
// without depending on forest.Fit's split-selection behavior.
func constantForest(t *testing.T, value float64) *forest.Forest {
	t.Helper()
	X := make([][]float64, 20)
	y := make([]float64, 20)
	for i := range X {
		X[i] = make([]float64, features.NumFeatures)
		y[i] = value
	}
	cfg := forest.DefaultConfig()
	cfg.NumTrees = 3
	cfg.MinLeafSamples = 1
	return forest.Fit(X, y, cfg)
}

func TestPredictStationProducesFullHorizonAndHandlesMissingModel(t *testing.T) {
	cutoff := time.Date(2026, 1, 8, 12, 0, 0, 0, time.UTC)
	const horizonSteps = 12 // 1 hour at 5-minute steps

	holidays := map[string]store.DayInfo{}
	weather := map[string]int{}
	for d := cutoff.AddDate(0, 0, -10); !d.After(cutoff.AddDate(0, 0, 3)); d = d.AddDate(0, 0, 1) {
		key := d.Format("2006-01-02")
		holidays[key] = store.DayInfo{IsSchool: true}
		weather[key] = 1
	}

	// seed 8 days of history so lag1w/mean7d are always satisfiable
	from := cutoff.Add(-8 * 24 * time.Hour)
	occA := map[int64]float64{}
	for ts := from; !ts.After(cutoff); ts = ts.Add(features.StepSeconds * time.Second) {
		occA[ts.Unix()] = 0.3
	}

	db, err := store.Open(t.TempDir() + "/test.db")
	if err != nil {
		t.Fatalf("opening store: %v", err)
	}
	defer db.Close()

	stationA := store.Station{Scode: "A", StationType: "ParkingStation", Capacity: 100}
	stationC := store.Station{Scode: "C", StationType: "ParkingStation", Capacity: 10}
	if err := db.UpsertStations([]store.Station{stationA, stationC}); err != nil {
		t.Fatalf("UpsertStations: %v", err)
	}
	var points []store.OccPoint
	for ts, v := range occA {
		points = append(points, store.OccPoint{TS: time.Unix(ts, 0).UTC(), Value: v * stationA.Capacity})
	}
	if err := db.InsertOccupancy("A", points); err != nil {
		t.Fatalf("InsertOccupancy: %v", err)
	}

	cfg := config.Env{ForestLoPercentile: 0.1, ForestHiPercentile: 0.9}

	fcA := predictStation(db, stationA, constantForest(t, 0.4), holidays, weather, from, cutoff, horizonSteps, cfg)
	fcC := predictStation(db, stationC, nil, holidays, weather, from, cutoff, horizonSteps, cfg) // no trained model

	if len(fcA.Points) != horizonSteps {
		t.Fatalf("A: got %d points, want %d", len(fcA.Points), horizonSteps)
	}
	if len(fcC.Points) != horizonSteps {
		t.Fatalf("C: got %d points, want %d", len(fcC.Points), horizonSteps)
	}

	for _, p := range fcA.Points {
		if p.Mean == nil {
			t.Fatalf("A: expected a non-null forecast (has model + history)")
		}
		if *p.Mean < 0 || *p.Mean > 100 {
			t.Fatalf("A: forecast %v outside [0, capacity]", *p.Mean)
		}
		if p.Lo == nil || p.Hi == nil || *p.Lo > *p.Mean || *p.Hi < *p.Mean {
			t.Fatalf("A: lo/mean/hi out of order: %v/%v/%v", *p.Lo, *p.Mean, *p.Hi)
		}
	}

	for _, p := range fcC.Points {
		if p.Mean != nil || p.Lo != nil || p.Hi != nil {
			t.Fatalf("C: expected an all-null forecast (no trained model), got %+v", p)
		}
	}
}

func TestPredictStationHorizonsAreIndependent(t *testing.T) {
	// A direct-horizon model carries no state between steps: the forecast
	// for the first hour must be identical whether or not later, longer
	// horizons are also requested — a recursive rollout would fail this,
	// since a longer requested horizon means more compounding by the time
	// you reach any given step.
	cutoff := time.Date(2026, 1, 8, 12, 0, 0, 0, time.UTC)
	holidays := map[string]store.DayInfo{}
	weather := map[string]int{}
	for d := cutoff.AddDate(0, 0, -10); !d.After(cutoff.AddDate(0, 0, 3)); d = d.AddDate(0, 0, 1) {
		key := d.Format("2006-01-02")
		holidays[key] = store.DayInfo{IsSchool: true}
		weather[key] = 1
	}

	from := cutoff.Add(-8 * 24 * time.Hour)
	occA := map[int64]float64{}
	for ts := from; !ts.After(cutoff); ts = ts.Add(features.StepSeconds * time.Second) {
		occA[ts.Unix()] = 0.3
	}

	db, err := store.Open(t.TempDir() + "/test.db")
	if err != nil {
		t.Fatalf("opening store: %v", err)
	}
	defer db.Close()

	station := store.Station{Scode: "A", StationType: "ParkingStation", Capacity: 100}
	if err := db.UpsertStations([]store.Station{station}); err != nil {
		t.Fatalf("UpsertStations: %v", err)
	}
	var points []store.OccPoint
	for ts, v := range occA {
		points = append(points, store.OccPoint{TS: time.Unix(ts, 0).UTC(), Value: v * station.Capacity})
	}
	if err := db.InsertOccupancy("A", points); err != nil {
		t.Fatalf("InsertOccupancy: %v", err)
	}

	cfg := config.Env{ForestLoPercentile: 0.1, ForestHiPercentile: 0.9}
	model := constantForest(t, 0.4)

	full := predictStation(db, station, model, holidays, weather, from, cutoff, 48, cfg) // 4h at 5-min steps
	short := predictStation(db, station, model, holidays, weather, from, cutoff, 12, cfg) // 1h at 5-min steps

	for i := range short.Points {
		if *full.Points[i].Mean != *short.Points[i].Mean {
			t.Fatalf("step %d: expected the same prediction regardless of the requested horizon length: %v (full) vs %v (short)",
				i, *full.Points[i].Mean, *short.Points[i].Mean)
		}
	}
}
