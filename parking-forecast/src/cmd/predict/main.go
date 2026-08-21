// SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>
//
// SPDX-License-Identifier: AGPL-3.0-or-later

// Command predict evaluates every station's forest directly, once per
// forecast step, anchored on the same cutoff (the most recent real
// observation) each time — then writes the legacy result.json (publishing
// to ODH/BDP is planned but not implemented yet). It replaces
// process4-prediction.py + process5-generate-json.py. Scheduled hourly as
// its own k8s CronJob.
//
// This is deliberately not a recursive rollout: an earlier version stepped
// through the horizon one 5-minute tick at a time, feeding each step's own
// prediction back in as if it were a real observation for the next step's
// lag features. That compounds error — a backtest against the live
// production model showed it losing ground steadily past ~90 minutes out,
// worse than the live model by 4 hours, precisely because early mistakes
// dragged every later step down with them. Evaluating every horizon
// directly from the same real anchor (see features.Build and
// features.TrainingHorizonsMinutes, which cmd/train fits the forest across)
// avoids that entirely: a mistake at 30 minutes has no way to influence the
// prediction at 4 hours, because both are computed independently from the
// same unmodified history.
package main

import (
	"context"
	"log/slog"
	"time"

	"github.com/noi-techpark/opendatahub-go-sdk/ingest/ms"
	"github.com/noi-techpark/opendatahub-go-sdk/tel"

	"parking-forecast/internal/config"
	"parking-forecast/internal/features"
	"parking-forecast/internal/forest"
	"parking-forecast/internal/publish"
	"parking-forecast/internal/store"
)

// predictSafetyMargin accounts for ingest's cadence: by the time predict
// runs, the freshest occupancy sample might lag "now" by a bit. Stations
// whose actual last sample is still older than this get an all-null
// forecast (see readme-for-data-consumers.md: "this happens when a parking
// station has not sent up to date data"), same intent as before.
const predictSafetyMargin = 10 * time.Minute

// historyBuffer bounds how much history gets loaded per station: nothing
// beyond it is ever read (the longest lookback any feature needs is lag1w).
const historyBuffer = 8 * 24 * time.Hour

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
	slog.Info("prediction run starting", "stations", len(stations))

	holidayMap, err := db.AllHolidays()
	ms.FailOnError(ctx, err, "loading holidays")
	weatherMap, err := db.AllWeather()
	ms.FailOnError(ctx, err, "loading weather")

	cutoff := time.Now().UTC().Add(-predictSafetyMargin).Truncate(features.StepSeconds * time.Second)
	horizonSteps := cfg.HoursToPredict * 60 / (features.StepSeconds / 60)
	from := cutoff.Add(-historyBuffer)

	slog.Info("forecast window", "cutoff", cutoff, "horizonSteps", horizonSteps)

	models, err := loadModels(db, stations)
	if err != nil {
		slog.Error("loading models", "err", err)
	}

	forecasts := make([]publish.StationForecast, 0, len(stations))
	for _, s := range stations {
		forecasts = append(forecasts, predictStation(db, s, models[s.Scode], holidayMap, weatherMap, from, cutoff, horizonSteps, cfg))
	}

	if err := publish.WriteResultJSON(cfg.ResultJsonPath, cutoff.Add(features.StepSeconds*time.Second), cfg.HoursToPredict, cfg.ModelVersion, forecasts); err != nil {
		slog.Error("writing legacy result.json failed", "err", err)
	} else {
		slog.Info("wrote legacy result.json", "path", cfg.ResultJsonPath)
	}

	slog.Info("prediction run complete")
}

// predictStation evaluates s's forest directly at every step of the
// horizon, all anchored on the same cutoff. A nil model or unloadable
// history yields an all-null forecast (station not yet forecastable), same
// as a station whose data hasn't caught up to cutoff.
func predictStation(
	db *store.DB,
	s store.Station,
	model *forest.Forest,
	holidayMap map[string]store.DayInfo,
	weatherMap map[string]int,
	from, cutoff time.Time,
	horizonSteps int,
	cfg config.Env,
) publish.StationForecast {
	fc := publish.StationForecast{Scode: s.Scode, Points: make([]publish.Point, 0, horizonSteps)}

	nullForecast := func() publish.StationForecast {
		for step := 1; step <= horizonSteps; step++ {
			fc.Points = append(fc.Points, publish.Point{TS: cutoff.Add(time.Duration(step) * features.StepSeconds * time.Second)})
		}
		return fc
	}

	if model == nil {
		return nullForecast()
	}

	rawOcc, err := db.OccupancyMap(s.Scode, from, cutoff)
	if err != nil {
		slog.Error("loading occupancy history", "scode", s.Scode, "err", err)
		return nullForecast()
	}
	occ := features.Normalize(rawOcc, s.Capacity)
	mean7d := features.RollingMean7d(occ, cutoff, cutoff)

	inputs := features.Inputs{Occupancy: occ, Mean7d: mean7d, Holidays: holidayMap, Weather: weatherMap}

	for step := 1; step <= horizonSteps; step++ {
		ts := cutoff.Add(time.Duration(step) * features.StepSeconds * time.Second)

		row, ok := features.Build(ts, cutoff, inputs)
		if !ok {
			fc.Points = append(fc.Points, publish.Point{TS: ts})
			continue
		}

		meanRatio, loRatio, hiRatio := model.PredictStats(row[:], cfg.ForestLoPercentile, cfg.ForestHiPercentile)

		capacity := s.Capacity
		lo := features.Denormalize(loRatio, capacity)
		mean := features.Denormalize(meanRatio, capacity)
		hi := features.Denormalize(hiRatio, capacity)
		fc.Points = append(fc.Points, publish.Point{TS: ts, Lo: &lo, Mean: &mean, Hi: &hi})
	}
	return fc
}

func loadModels(db *store.DB, stations []store.Station) (map[string]*forest.Forest, error) {
	out := map[string]*forest.Forest{}
	for _, s := range stations {
		blob, _, ok, err := db.LoadModel(s.Scode)
		if err != nil {
			return out, err
		}
		if !ok {
			continue
		}
		f, err := forest.Unmarshal(blob)
		if err != nil {
			slog.Error("unmarshaling forest, skipping station", "scode", s.Scode, "err", err)
			continue
		}
		out[s.Scode] = f
	}
	return out, nil
}
