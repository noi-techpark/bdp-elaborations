// SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>
//
// SPDX-License-Identifier: AGPL-3.0-or-later

package features

import (
	"math"
	"testing"
	"time"

	"parking-forecast/internal/store"
)

func fullInputs(anchor time.Time) Inputs {
	unix := anchor.Unix()
	return Inputs{
		Occupancy: map[int64]float64{
			unix: 0.1, unix - StepSeconds: 0.1, unix - lag1h: 0.1,
			unix - lag1d: 0.1, unix - lag1w: 0.1,
		},
		Mean7d:   map[int64]float64{unix: 0.3},
		Holidays: map[string]store.DayInfo{anchor.Format("2006-01-02"): {}},
		Weather:  map[string]int{anchor.Format("2006-01-02"): 1},
	}
}

func TestSeasonalFeatureWrapsAroundNewYear(t *testing.T) {
	dec31 := time.Date(2025, 12, 31, 12, 0, 0, 0, time.UTC)
	jan1 := time.Date(2026, 1, 1, 12, 0, 0, 0, time.UTC)
	jul1 := time.Date(2026, 7, 1, 12, 0, 0, 0, time.UTC)

	// anchor == target reproduces the old one-step behavior; only the
	// calendar features (which describe target) are under test here.
	xDec31, ok := Build(dec31, dec31, fullInputs(dec31))
	if !ok {
		t.Fatalf("expected ok=true for dec31")
	}
	xJan1, ok := Build(jan1, jan1, fullInputs(jan1))
	if !ok {
		t.Fatalf("expected ok=true for jan1")
	}
	xJul1, ok := Build(jul1, jul1, fullInputs(jul1))
	if !ok {
		t.Fatalf("expected ok=true for jul1")
	}

	distNewYear := math.Hypot(xDec31[IdxSinSeason]-xJan1[IdxSinSeason], xDec31[IdxCosSeason]-xJan1[IdxCosSeason])
	distHalfYear := math.Hypot(xDec31[IdxSinSeason]-xJul1[IdxSinSeason], xDec31[IdxCosSeason]-xJul1[IdxCosSeason])

	if distNewYear >= distHalfYear {
		t.Fatalf("Dec 31 should be much closer to Jan 1 than to Jul 1 in season space: distNewYear=%v distHalfYear=%v", distNewYear, distHalfYear)
	}
	if distNewYear > 0.1 {
		t.Fatalf("Dec 31 / Jan 1 should be nearly identical in season space, got distance %v", distNewYear)
	}
}

func TestRollingMean7dExcludesCurrentPoint(t *testing.T) {
	base := time.Date(2026, 1, 8, 12, 0, 0, 0, time.UTC) // an arbitrary Thursday noon
	occ := map[int64]float64{}
	// constant 0.5 for the whole week before base, then a spike exactly at base
	for t := base.Add(-8 * 24 * time.Hour); !t.After(base); t = t.Add(StepSeconds * time.Second) {
		occ[t.Unix()] = 0.5
	}
	occ[base.Unix()] = 999 // must NOT leak into its own rolling mean

	out := RollingMean7d(occ, base.Add(-1*time.Hour), base)
	got, ok := out[base.Unix()]
	if !ok {
		t.Fatalf("expected a value at base ts")
	}
	if math.Abs(got-0.5) > 1e-9 {
		t.Fatalf("rolling mean at base = %v, want ~0.5 (must not include the current point)", got)
	}
}

func TestRollingMean7dMissingWhenNoHistory(t *testing.T) {
	base := time.Date(2026, 1, 8, 12, 0, 0, 0, time.UTC)
	occ := map[int64]float64{base.Unix(): 1.0}
	out := RollingMean7d(occ, base, base)
	if _, ok := out[base.Unix()]; ok {
		t.Fatalf("expected no rolling mean when there's no preceding history")
	}
}

func TestBuildRequiresAllMandatoryInputs(t *testing.T) {
	anchor := time.Date(2026, 1, 8, 8, 5, 0, 0, time.UTC)
	full := fullInputs(anchor)

	if _, ok := Build(anchor, anchor, full); !ok {
		t.Fatalf("expected ok=true when all mandatory inputs are present")
	}

	missingLag := full
	missingLag.Occupancy = map[int64]float64{anchor.Unix(): 0.1} // missing the rest
	if _, ok := Build(anchor, anchor, missingLag); ok {
		t.Fatalf("expected ok=false when a lag is missing")
	}

	missingWeather := full
	missingWeather.Weather = map[string]int{}
	if _, ok := Build(anchor, anchor, missingWeather); ok {
		t.Fatalf("expected ok=false when weather is missing")
	}
}

func TestBuildDirectHorizonUsesAnchorLagsAndTargetCalendar(t *testing.T) {
	anchor := time.Date(2026, 1, 8, 8, 5, 0, 0, time.UTC) // a Thursday
	full := fullInputs(anchor)
	// target's own occupancy/weather/holidays are deliberately absent from
	// full — a direct-horizon prediction must not need them.
	target := anchor.Add(2 * time.Hour)

	row, ok := Build(target, anchor, full)
	if !ok {
		t.Fatalf("expected ok=true predicting 2h ahead from a fixed anchor without any data at target")
	}
	if row[IdxHorizonMinutes] != 120 {
		t.Fatalf("expected IdxHorizonMinutes=120, got %v", row[IdxHorizonMinutes])
	}
	if row[IdxLagNow] != 0.1 || row[IdxLagPrev5m] != 0.1 {
		t.Fatalf("expected lag features to come from the anchor, got LagNow=%v LagPrev5m=%v", row[IdxLagNow], row[IdxLagPrev5m])
	}

	// Calendar features must describe target, not anchor: pick a target on
	// a different day to make sure day-of-week actually moved.
	nextDay := anchor.Add(24 * time.Hour)
	full.Holidays[nextDay.Format("2006-01-02")] = store.DayInfo{}
	full.Weather[nextDay.Format("2006-01-02")] = 1
	rowNextDay, ok := Build(nextDay, anchor, full)
	if !ok {
		t.Fatalf("expected ok=true predicting into the next day")
	}
	if rowNextDay[IdxSinDow] == row[IdxSinDow] && rowNextDay[IdxCosDow] == row[IdxCosDow] {
		t.Fatalf("expected day-of-week features to reflect target's date, not anchor's")
	}
}
