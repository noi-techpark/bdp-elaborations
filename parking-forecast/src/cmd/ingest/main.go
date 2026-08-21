// SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>
//
// SPDX-License-Identifier: AGPL-3.0-or-later

// Command ingest refreshes the local SQLite cache: station metadata, holiday
// and weather reference data, and — incrementally, in batches of
// stationBatchSize stations per request — occupancy history. It replaces
// data-raw-get.js/data-raw-get-diff.js/data-holidays-get.*/data-meteo-get.sh.
// Scheduled frequently (e.g. every 15 minutes) as its own k8s CronJob.
package main

import (
	"context"
	"log/slog"
	"sort"
	"sync"
	"time"

	"github.com/noi-techpark/opendatahub-go-sdk/elab"
	"github.com/noi-techpark/opendatahub-go-sdk/ingest/ms"
	"github.com/noi-techpark/opendatahub-go-sdk/tel"

	"parking-forecast/internal/config"
	"parking-forecast/internal/holidays"
	"parking-forecast/internal/odh"
	"parking-forecast/internal/store"
	"parking-forecast/internal/weather"
)

// minHistoryStart is the arbitrary "dawn of time" the old pipeline used
// (process1-raw-to-signals.py's MIN_TS) for stations we've never cached
// anything for yet.
var minHistoryStart = time.Date(2022, 1, 1, 0, 0, 0, 0, time.UTC)

const (
	// fetchConcurrency bounds how many occupancy-history requests are in
	// flight at once.
	fetchConcurrency = 8
	// maxBatchStations bounds how much history a single request can pull in
	// one go, independent of URL length (see maxBatchURLChars).
	maxBatchStations = 200
	// maxBatchURLChars mirrors the 1000-char safety margin
	// opendatahub-go-sdk/elab's own bucketing uses for a station code
	// filter (see elab.wideTypeFollower.MaxUrlLength) — batching (instead
	// of one request per station) is what keeps ingest's request count
	// roughly constant as the station count grows into the thousands.
	// Stations are sorted by their catch-up start first (see
	// ingestOccupancy), so almost every batch ends up being stations that
	// are all equally caught-up already, and only brand-new stations
	// (needing their full history) end up batched together separately.
	maxBatchURLChars = 1000
)

func main() {
	ctx := context.Background()

	var cfg config.Env
	ms.InitWithEnv(ctx, "", &cfg)
	defer tel.FlushOnPanic()

	db, err := store.Open(cfg.DbPath)
	ms.FailOnError(ctx, err, "opening store")
	defer db.Close()

	client := odh.New(cfg)

	slog.Info("fetching station metadata")
	stations, err := client.FetchStations()
	ms.FailOnError(ctx, err, "fetching stations")
	slog.Info("fetched stations", "count", len(stations))

	storeStations := make([]store.Station, 0, len(stations))
	for _, s := range stations {
		storeStations = append(storeStations, store.Station{
			Scode:       s.Scode,
			Name:        s.Name,
			StationType: s.StationType,
			Lat:         s.Lat,
			Lon:         s.Lon,
			Capacity:    s.Capacity,
			Active:      true,
		})
	}
	ms.FailOnError(ctx, db.UpsertStations(storeStations), "upserting stations")

	slog.Info("refreshing holidays cache")
	if err := holidays.FetchAndCache(cfg.TourismApiBaseUrl, db); err != nil {
		slog.Error("refreshing holidays failed, keeping previous cache", "err", err)
	}

	slog.Info("refreshing weather cache")
	if err := weather.FetchAndCache(cfg.TourismApiBaseUrl, db); err != nil {
		slog.Error("refreshing weather failed, keeping previous cache", "err", err)
	}

	ingestOccupancy(client, db, stations)

	retentionCutoff := time.Now().UTC().AddDate(0, 0, -cfg.OccupancyRetentionDays)
	if purged, err := db.PurgeOccupancyBefore(retentionCutoff); err != nil {
		slog.Error("purging old occupancy history failed", "err", err)
	} else if purged > 0 {
		slog.Info("purged old occupancy history", "cutoff", retentionCutoff, "rowsRemoved", purged)
	}

	slog.Info("ingest complete")
}

type pendingStation struct {
	station odh.StationInfo
	from    time.Time
	to      time.Time
}

func ingestOccupancy(client *odh.Client, db *store.DB, stations []odh.StationInfo) {
	byType := map[string][]pendingStation{}

	for _, s := range stations {
		if !s.HasOccupancyTS {
			continue // ODH has no data for this station at all yet
		}

		from := minHistoryStart
		if cursor, ok, err := db.LastOccupancyTS(s.Scode); err != nil {
			slog.Error("reading ingest cursor", "scode", s.Scode, "err", err)
			continue
		} else if ok {
			from = cursor.Add(time.Second)
		}

		to := s.LastOccupancyTS.Add(time.Millisecond) // RequestHistory's range is half-open
		if !to.After(from) {
			continue // already caught up
		}

		byType[s.StationType] = append(byType[s.StationType], pendingStation{station: s, from: from, to: to})
	}

	var wg sync.WaitGroup
	sem := make(chan struct{}, fetchConcurrency)

	for stationType, pending := range byType {
		// Sorting by catch-up start clusters stations that are already
		// caught up (the overwhelming majority on any given run) into
		// large batches with a narrow, cheap time range, while stations
		// that need their full history naturally end up batched together
		// (or alone) instead of dragging an unrelated batch's range back
		// to 2022.
		sort.Slice(pending, func(i, j int) bool { return pending[i].from.Before(pending[j].from) })

		for _, batch := range chunkByURLLength(pending) {
			wg.Add(1)
			sem <- struct{}{}
			go func(stationType string, batch []pendingStation) {
				defer wg.Done()
				defer func() { <-sem }()
				fetchAndCacheBatch(client, db, stationType, batch)
			}(stationType, batch)
		}
	}

	wg.Wait()
}

// chunkByURLLength splits pending into batches that respect both
// maxBatchStations and maxBatchURLChars.
func chunkByURLLength(pending []pendingStation) [][]pendingStation {
	var chunks [][]pendingStation
	var current []pendingStation
	urlChars := 0

	for _, p := range pending {
		codeLen := len(p.station.Scode) + 3 // quotes + comma/escaping overhead, same estimate elab uses
		if len(current) > 0 && (len(current) >= maxBatchStations || urlChars+codeLen > maxBatchURLChars) {
			chunks = append(chunks, current)
			current = nil
			urlChars = 0
		}
		current = append(current, p)
		urlChars += codeLen
	}
	if len(current) > 0 {
		chunks = append(chunks, current)
	}
	return chunks
}

func fetchAndCacheBatch(client *odh.Client, db *store.DB, stationType string, batch []pendingStation) {
	from, to := batch[0].from, batch[0].to
	scodes := make([]string, len(batch))
	for i, p := range batch {
		scodes[i] = p.station.Scode
		if p.from.Before(from) {
			from = p.from
		}
		if p.to.After(to) {
			to = p.to
		}
	}

	measurements, err := client.FetchOccupancyHistory(stationType, scodes, from, to)
	if err != nil {
		slog.Error("fetching occupancy history batch", "stationType", stationType, "stations", len(batch), "err", err)
		return
	}

	byStation := map[string][]store.OccPoint{}
	for _, m := range measurements {
		if m.Value.Type != elab.MTypeFloat || m.Value.Num == nil {
			continue
		}
		byStation[m.StationCode] = append(byStation[m.StationCode], store.OccPoint{TS: m.Timestamp.Time, Value: *m.Value.Num})
	}

	for _, p := range batch {
		// The batch's shared "from" can be earlier than this particular
		// station's own cursor (it's the min across the batch); drop
		// anything at or before its cursor to avoid redundant writes.
		var points []store.OccPoint
		for _, pt := range byStation[p.station.Scode] {
			if !pt.TS.Before(p.from) {
				points = append(points, pt)
			}
		}
		if err := db.InsertOccupancy(p.station.Scode, points); err != nil {
			slog.Error("caching occupancy history", "scode", p.station.Scode, "err", err)
		}
	}
}
