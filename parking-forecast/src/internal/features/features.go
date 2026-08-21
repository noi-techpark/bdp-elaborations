// SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>
//
// SPDX-License-Identifier: AGPL-3.0-or-later

// Package features builds the fixed-size feature row the forest model is
// trained and evaluated on, shared by cmd/train and cmd/predict. Unlike the
// old pipeline, the feature count never grows with the number of stations
// (no one-hot station index) or with time resolution (no one-hot hour
// column) — this is what lets a single set of hyperparameters and a fast,
// independent per-station fit scale to many more stations.
package features

import (
	"math"
	"sort"
	"time"

	"parking-forecast/internal/store"
)

// Feature indices. Every row has exactly this many columns, in this order.
const (
	IdxSinTime = iota
	IdxCosTime
	IdxSinDow
	IdxCosDow
	IdxSinSeason
	IdxCosSeason
	IdxIsHoliday
	IdxIsSchool
	IdxWeather
	IdxLagNow    // occupancy at the anchor itself (the most recent known observation)
	IdxLagPrev5m // occupancy 5 minutes before the anchor (short-term trend/direction)
	IdxLag1h
	IdxLag1d
	IdxLag1w
	IdxMean7d
	IdxHorizonMinutes // minutes from the anchor to the timestamp being predicted
	NumFeatures
)

const (
	StepSeconds = 300 // 5 minutes, matches the ODH parking occupancy sample period
	lag1h       = 12 * StepSeconds
	lag1d       = 288 * StepSeconds
	lag1w       = 2016 * StepSeconds
	mean7dSpan  = 7 * 24 * 60 * 60 // 7 days, in seconds
)

// TrainingHorizonsMinutes are the horizons cmd/train generates labeled rows
// for, and the range cmd/predict evaluates by varying IdxHorizonMinutes
// against a fixed anchor rather than recursively feeding predictions back in
// as if they were real observations (see package predict's doc for why: a
// single-step recursive rollout compounds each step's error into every step
// after it). A model trained across a spread of horizons generalizes to
// horizons in between reasonably well since IdxHorizonMinutes is an ordinary
// numeric feature, so this doesn't need to enumerate every 5-minute tick out
// to the full forecast window.
var TrainingHorizonsMinutes = []int{30, 60, 90, 120, 150, 180, 210, 240}

// Inputs bundles everything Build needs to read for one station. Occupancy
// and Mean7d are keyed by unix timestamp (UTC, 5-minute aligned);
// Holidays/Weather are keyed by ISO date (YYYY-MM-DD).
type Inputs struct {
	// Occupancy ratio (occupancy/capacity) for this station.
	Occupancy map[int64]float64
	Mean7d    map[int64]float64
	Holidays  map[string]store.DayInfo
	Weather   map[string]int
}

// Build constructs the feature row for predicting occupancy at target,
// anchored on the most recent known observation at anchor (anchor <=
// target). Calendar features (time of day, day of week, season, holiday,
// weather) describe target, since that's the point being forecast; the lag
// and rolling-mean features describe anchor, since that's the most recent
// real data available — occupancy near target's own timestamp can't be used
// without leaking the very thing being predicted. ok is false when mandatory data
// (a lag, calendar or weather info) isn't available yet — the caller should
// skip this row (training) or treat the station as not-yet-forecastable at
// this point (prediction).
func Build(target, anchor time.Time, in Inputs) (x [NumFeatures]float64, ok bool) {
	target = target.UTC()
	anchor = anchor.UTC()
	unix := target.Unix()
	anchorUnix := anchor.Unix()

	minuteOfDay := float64(target.Hour()*60 + target.Minute())
	angleDay := 2 * math.Pi * minuteOfDay / 1440
	x[IdxSinTime] = math.Sin(angleDay)
	x[IdxCosTime] = math.Cos(angleDay)

	angleWeek := 2 * math.Pi * float64(target.Weekday()) / 7
	x[IdxSinDow] = math.Sin(angleWeek)
	x[IdxCosDow] = math.Cos(angleWeek)

	// Day-of-year, cyclical: the only way the model can learn annual
	// seasonality (tourist/ski season vs. off-season, etc.) at all — without
	// it, retaining more than a few weeks of history wouldn't teach the
	// model anything a shorter window doesn't already cover.
	angleYear := 2 * math.Pi * float64(target.YearDay()-1) / 365.25
	x[IdxSinSeason] = math.Sin(angleYear)
	x[IdxCosSeason] = math.Cos(angleYear)

	date := target.Format("2006-01-02")
	day, hasDay := in.Holidays[date]
	if !hasDay {
		return x, false
	}
	x[IdxIsHoliday] = boolToFloat(day.IsHoliday)
	x[IdxIsSchool] = boolToFloat(day.IsSchool)

	symbol, hasWeather := in.Weather[date]
	if !hasWeather {
		return x, false
	}
	x[IdxWeather] = float64(symbol)

	lagNow, okNow := in.Occupancy[anchorUnix]
	lagPrev5m, ok5 := in.Occupancy[anchorUnix-StepSeconds]
	lag1hv, ok1h := in.Occupancy[anchorUnix-lag1h]
	lag1dv, ok1d := in.Occupancy[anchorUnix-lag1d]
	lag1wv, ok1w := in.Occupancy[anchorUnix-lag1w]
	if !okNow || !ok5 || !ok1h || !ok1d || !ok1w {
		return x, false
	}
	x[IdxLagNow] = lagNow
	x[IdxLagPrev5m] = lagPrev5m
	x[IdxLag1h] = lag1hv
	x[IdxLag1d] = lag1dv
	x[IdxLag1w] = lag1wv

	mean7d, hasMean := in.Mean7d[anchorUnix]
	if !hasMean {
		return x, false
	}
	x[IdxMean7d] = mean7d

	x[IdxHorizonMinutes] = float64(unix-anchorUnix) / 60

	return x, true
}

func boolToFloat(b bool) float64 {
	if b {
		return 1
	}
	return 0
}

// Normalize converts raw occupancy counts to ratios (occupancy/capacity) so
// that lag and mean features are comparable across stations of different
// sizes. If capacity is unknown (<= 0), values pass through unchanged and
// the model effectively operates on raw counts for that station. Negative
// sensor readings are clamped to 0.
func Normalize(raw map[int64]float64, capacity float64) map[int64]float64 {
	out := make(map[int64]float64, len(raw))
	for ts, v := range raw {
		if v < 0 {
			v = 0
		}
		if capacity > 0 {
			v /= capacity
		}
		out[ts] = v
	}
	return out
}

// Denormalize converts a model prediction back to occupancy-count units,
// clamped to [0, capacity] when capacity is known.
func Denormalize(ratio, capacity float64) float64 {
	v := ratio
	if capacity > 0 {
		v *= capacity
		if v > capacity {
			v = capacity
		}
	}
	if v < 0 {
		v = 0
	}
	return v
}

// RollingMean7d computes, for every timestamp present in occ within
// [from, to], the mean of occ over the preceding 7 days ending at ts-5min
// (i.e. it never looks at ts itself, so it can't leak the training target).
// Uses a sliding-window sum over the sorted timestamps, O(n log n), instead
// of recomputing a mean over ~2000 samples per row.
func RollingMean7d(occ map[int64]float64, from, to time.Time) map[int64]float64 {
	return rollingMean(occ, from, to, mean7dSpan)
}

func rollingMean(occ map[int64]float64, from, to time.Time, spanSeconds int64) map[int64]float64 {
	ts := make([]int64, 0, len(occ))
	for t := range occ {
		ts = append(ts, t)
	}
	sort.Slice(ts, func(i, j int) bool { return ts[i] < ts[j] })

	out := map[int64]float64{}
	sum := 0.0
	count := 0
	lo, hi := 0, 0 // window currently covers ts[lo:hi]

	fromUnix, toUnix := from.Unix(), to.Unix()
	for cur := fromUnix; cur <= toUnix; cur += StepSeconds {
		windowEnd := cur - StepSeconds   // inclusive upper bound (strictly before cur)
		windowStart := cur - spanSeconds // inclusive lower bound

		// include newly-eligible points ahead of the window
		for hi < len(ts) && ts[hi] <= windowEnd {
			sum += occ[ts[hi]]
			count++
			hi++
		}
		// drop points that have fallen out of the window behind it
		for lo < hi && ts[lo] < windowStart {
			sum -= occ[ts[lo]]
			count--
			lo++
		}

		if count > 0 {
			out[cur] = sum / float64(count)
		}
	}
	return out
}
