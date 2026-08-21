// SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>
//
// SPDX-License-Identifier: AGPL-3.0-or-later

// Command train fits one Random Forest per active station from the cached
// occupancy/holiday/weather history and persists it to SQLite. It replaces
// process2-signals-to-trainingdata.py + process3-fit-model.py and the 5x
// dnn_model* TensorFlow ensemble: every station is fit independently and in
// parallel, so training cost grows linearly with station count instead of
// with (station count)^2 like the old one-hot-encoded joint model.
// Scheduled nightly as its own k8s CronJob.
//
// Unlike a one-step model that's rolled forward recursively at prediction
// time (feeding each step's own prediction back in as if it were real, and
// so compounding error into every step after it — measured directly in a
// backtest against the previous approach), each station's forest is trained
// directly on a spread of horizons (features.TrainingHorizonsMinutes): every
// training row is "given what was known as of some anchor time, what was
// the occupancy H minutes later," for many different H. cmd/predict then
// evaluates the horizon it actually wants directly from a single fixed
// anchor, with no recursion at all.
package main

import (
	"context"
	"log/slog"
	"runtime"
	"sync"
	"time"

	"github.com/noi-techpark/opendatahub-go-sdk/ingest/ms"
	"github.com/noi-techpark/opendatahub-go-sdk/tel"

	"parking-forecast/internal/config"
	"parking-forecast/internal/features"
	"parking-forecast/internal/forest"
	"parking-forecast/internal/store"
)

func main() {
	ctx := context.Background()

	var cfg config.Env
	ms.InitWithEnv(ctx, "", &cfg)
	defer tel.FlushOnPanic()

	db, err := store.Open(cfg.DbPath)
	ms.FailOnError(ctx, err, "opening store")
	defer db.Close()

	stations, err := db.ActiveStations()
	ms.FailOnError(ctx, err, "loading stations")
	slog.Info("training run starting", "stations", len(stations))

	holidayMap, err := db.AllHolidays()
	ms.FailOnError(ctx, err, "loading holidays")

	weatherMap, err := db.AllWeather()
	ms.FailOnError(ctx, err, "loading weather")

	forestCfg := forest.Config{
		NumTrees:         cfg.ForestTrees,
		MaxDepth:         cfg.ForestMaxDepth,
		MinLeafSamples:   cfg.ForestMinLeafSamples,
		RowSubsample:     cfg.ForestRowSubsample,
		FeatureSubsample: cfg.ForestFeatureSubsample,
	}

	now := time.Now().UTC().Truncate(features.StepSeconds * time.Second)

	type outcome struct {
		scode string
		rows  int
		err   error
	}

	sem := make(chan struct{}, runtime.NumCPU())
	var wg sync.WaitGroup
	results := make(chan outcome, len(stations))

	for i, s := range stations {
		wg.Add(1)
		sem <- struct{}{}
		go func(s store.Station, seed int64) {
			defer wg.Done()
			defer func() { <-sem }()

			cfgCopy := forestCfg
			cfgCopy.Seed = seed

			rows, err := trainStation(db, s, holidayMap, weatherMap, now, cfgCopy, cfg.MinTrainRows)
			results <- outcome{scode: s.Scode, rows: rows, err: err}
		}(s, now.Unix()+int64(i))
	}

	go func() {
		wg.Wait()
		close(results)
	}()

	trained, skipped, failed := 0, 0, 0
	for r := range results {
		switch {
		case r.err != nil:
			failed++
			slog.Error("training station failed", "scode", r.scode, "err", r.err)
		case r.rows < cfg.MinTrainRows:
			skipped++
			slog.Warn("skipping station, not enough training data yet", "scode", r.scode, "rows", r.rows, "minRows", cfg.MinTrainRows)
		default:
			trained++
			slog.Info("trained station", "scode", r.scode, "rows", r.rows)
		}
	}

	slog.Info("training run complete", "trained", trained, "skipped", skipped, "failed", failed, "total", len(stations))
}

// trainStation builds the training matrix for one station and, if there's
// enough of it, fits and persists a forest. It always returns the row count
// (even below minRows) so the caller can log why a station was skipped.
func trainStation(
	db *store.DB,
	s store.Station,
	holidayMap map[string]store.DayInfo,
	weatherMap map[string]int,
	now time.Time,
	forestCfg forest.Config,
	minRows int,
) (int, error) {
	from, ok, err := db.EarliestOccupancyTS(s.Scode)
	if err != nil {
		return 0, err
	}
	if !ok {
		return 0, nil
	}
	// ODH's raw occupancy feed isn't reliably 5-minute-grid-aligned (sensor
	// jitter of a few seconds to a few minutes is common, see e.g. FAMAS
	// history) — the loop below and RollingMean7d below both stride from
	// this anchor in fixed StepSeconds steps, so an unaligned anchor would
	// carry that same offset through every lookup for the entire training
	// window, silently missing grid-aligned samples (like cmd/predict's
	// cutoff, which is already Truncate'd for this reason).
	from = from.Truncate(features.StepSeconds * time.Second)
	to := now

	rawOcc, err := db.OccupancyMap(s.Scode, from, to)
	if err != nil {
		return 0, err
	}
	occ := features.Normalize(rawOcc, s.Capacity)

	inputs := features.Inputs{
		Occupancy: occ,
		Mean7d:    features.RollingMean7d(occ, from, to),
		Holidays:  holidayMap,
		Weather:   weatherMap,
	}

	var X [][]float64
	var y []float64
	for anchorUnix := from.Unix(); anchorUnix <= to.Unix(); anchorUnix += features.StepSeconds {
		anchor := time.Unix(anchorUnix, 0).UTC()
		for _, h := range features.TrainingHorizonsMinutes {
			targetUnix := anchorUnix + int64(h)*60
			if targetUnix > to.Unix() {
				continue // no label for a horizon that hasn't happened yet
			}
			label, hasLabel := occ[targetUnix]
			if !hasLabel {
				continue
			}
			row, ok := features.Build(time.Unix(targetUnix, 0).UTC(), anchor, inputs)
			if !ok {
				continue
			}
			X = append(X, row[:])
			y = append(y, label)
		}
	}

	if len(X) < minRows {
		return len(X), nil
	}

	f := forest.Fit(X, y, forestCfg)
	blob, err := forest.Marshal(f)
	if err != nil {
		return len(X), err
	}

	if err := db.SaveModel(s.Scode, blob, time.Now().UTC(), len(X)); err != nil {
		return len(X), err
	}

	return len(X), nil
}
