<!--
SPDX-FileCopyrightText: 2021-2025 STA AG <info@sta.bz.it>
SPDX-FileContributor: Chris Mair <chris@1006.org>

SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>

SPDX-License-Identifier: CC0-1.0
-->

# Parking Forecast

Forecasts parking occupancy for [Open Data Hub](https://opendatahub.com/datasets) parking
stations and sensors, up to 48 hours ahead at 5-minute resolution.

This project was originally commissioned by STA and implemented by Thomas Auckenthaler and
Chris Mair, migrated to NOI in late 2025, and re-architected from the ground up in 2026 to scale
to many more stations at a fraction of the compute cost (see [Why this rewrite](#why-this-rewrite)).

## Overview

Three independent jobs, written in Go, share a single SQLite cache:

| Job               | Schedule (typical) | Does                                                                                          |
|-------------------|---------------------|------------------------------------------------------------------------------------------------|
| `cmd/ingest`      | every 15 min         | pulls new occupancy history from ODH, refreshes weather/holiday caches                          |
| `cmd/train`       | nightly              | fits one Random Forest per station from the cached history                                     |
| `cmd/predict`     | hourly                | forecasts 48h ahead directly per horizon and writes `result.json`                               |

Each is a standalone binary; in production each runs as its own Kubernetes CronJob against the
same container image (see `infrastructure/helm`), the pattern this repo's other elaborations
(`pollution_v2`, `traffic-a22-data-quality`) already use. Locally, `docker-compose.yml` runs the
same three binaries under `supercronic` for convenience.

## Model

One **Random Forest regressor per station**, trained independently from that station's own
history — not one joint model over every station like before (see below). Features, all fixed
in number regardless of station count or time resolution:

- time of day / day of week / day of year of the timestamp being predicted (all cyclical,
  `sin`/`cos` — the day-of-year pair is what lets the model learn annual seasonality, e.g.
  tourist/ski season vs. off-season)
- `is_holiday`, `is_school`, weather symbol, also for the timestamp being predicted
- own occupancy lags, all relative to the most recent real observation (the "anchor"): the anchor
  itself, 5 min before it, 1 hour before it, 1 day before it, 1 week before it
- own trailing 7-day mean as of the anchor
- the horizon itself (minutes from the anchor to the timestamp being predicted)

A station's own history was found to be the dominant signal in practice — a nearest-neighbor
occupancy feature was tried and measurably didn't improve accuracy (its information turned out to
be redundant with the station's own lags), so it isn't part of the feature set.

`cmd/predict` evaluates every requested horizon directly from the same anchor — no recursion.
An earlier version stepped through the horizon one 5-minute tick at a time, feeding each step's
own prediction back in as if it were a real observation for the next step's lags; a backtest
against the live production model showed that compounding error past ~90 minutes out, ending up
worse than the live model by 4 hours. Training the forest across a spread of horizons
(`features.TrainingHorizonsMinutes`) instead, with the horizon itself as an input feature, avoids
that: predicting 4 hours out never depends on a 30-minute guess having been right (see
`internal/features`'s and `cmd/predict`'s package docs for the details).

A forest's individual trees, evaluated separately, give the `lo`/`mean`/`hi` prediction interval
"for free" (a percentile spread across trees) — see `internal/forest`.

## Data retention & training cost

`train` refits each station's forest from scratch every night — Random Forests (like almost all
batch-trained models) can't be cheaply "updated" with just new data the way, say, a running
average can; a true incremental/streaming tree learner (e.g. Mondrian forests, Hoeffding trees)
is a real research area, not something to build for this. So instead of trying to make the
*algorithm* incremental, the retained *data* is bounded: `ingest` purges raw occupancy history
older than `OCCUPANCY_RETENTION_DAYS` (400 days by default — a bit over 13 months, enough for the
model to see one full annual cycle via the day-of-year feature above, plus a buffer for the
lag/rolling-window features) after every run (`store.PurgeOccupancyBefore`). That keeps both the
SQLite cache and nightly training cost flat forever, instead of growing with every station-year
ingested — and, since conditions this far back (capacity changes, road layout, etc.) are of
questionable relevance anyway, it's arguably a model-quality improvement too, not just a cost one.
Holiday/weather reference data is tiny (one row per calendar day, not per station) and isn't
purged.

## Output

`cmd/predict` writes `result.json` in the schema documented in
[`src/readme-for-data-consumers.md`](src/readme-for-data-consumers.md), served by the `nginx`
container/Deployment, for existing consumers.

Publishing forecasts as native Open Data Hub/BDP time series (the way every other elaboration in
this repo publishes results, e.g. `parking-free-slot-calculation` next to `occupied`) is planned
but deliberately not implemented yet — that migration will happen separately, later.

## Running locally

```sh
cp .env.example .env   # fill in ODH_CLIENT_SECRET
docker compose run --rm ingest
docker compose run --rm train
docker compose run --rm predict
cat data/result/result.json
```

`docker compose up` runs all three continuously on the schedules in `.env`
(`INGEST_CRON_SCHEDULE`/`TRAIN_CRON_SCHEDULE`/`PREDICT_CRON_SCHEDULE`), plus `nginx` serving
`result.json` on `NGINX_PORT`.

`src/go.mod`'s tests (`go test ./...`) don't need network access or credentials.

## Configuration

All configuration is environment variables, processed by `internal/config`; see that file for the
full list and defaults (Open Data Hub endpoints/credentials, station types, forest hyperparameters,
forecast horizon, `result.json` path).

## Repository layout

| Path                             | Purpose                                                              |
|-----------------------------------|------------------------------------------------------------------------|
| `src/cmd/ingest`                 | occupancy/weather/holiday cache refresh                              |
| `src/cmd/train`                  | per-station Random Forest fitting, across a spread of horizons        |
| `src/cmd/predict`                | direct per-horizon forecast (no recursion) + `result.json`            |
| `src/internal/store`             | SQLite cache (occupancy, reference data, station metadata, models)   |
| `src/internal/odh`               | Open Data Hub station/history client (wraps `go-timeseries-client`/`elab`'s read side) |
| `src/internal/weather`, `.../holidays` | Tourism Open Data Hub reference data                             |
| `src/internal/features`          | feature row construction, shared by train and predict                |
| `src/internal/forest`            | dependency-free Random Forest regressor                              |
| `src/internal/publish`           | legacy `result.json` renderer                                        |
| `src/graphs/`                    | tiny web app to plot `result.json`                                    |
| `infrastructure/docker`          | multi-stage Go build                                                  |
| `infrastructure/helm`            | Kubernetes CronJobs (ingest/train/predict), SQLite/result PVCs, nginx |

## Scaling headroom

Everything here is designed to comfortably absorb an order of magnitude more stations than it
runs against today:

- **ingest**'s occupancy fetch batches many stations into each ODH request instead of one request
  per station (grouped by station type, sorted by catch-up start so batches end up cheap, sized to
  stay under the same ~1000-char station-filter URL budget `opendatahub-go-sdk/elab` itself uses)
  — request count stays roughly constant as station count grows, instead of growing linearly.
- **train** fits one forest per station in parallel (bounded by CPU count); wall-clock time grows
  with station count only as fast as core count allows, and per-worker memory is bounded by one
  station's history, not the whole dataset.
- **predict** is O(stations × forecast steps), each step a cheap, independent forest evaluation —
  still comfortably sub-second-to-low-seconds at 10-100x today's station count.
- the SQLite cache itself is bounded regardless of station count or how many years this runs for
  — see [Data retention & training cost](#data-retention--training-cost).

## Why this rewrite

The old pipeline (bash + Node.js + Python/TensorFlow) trained a 5-way DNN ensemble jointly across
every station, one-hot-encoding the station index as a feature. That one-hot encoding is what made
it expensive and inflexible: every additional station added a column to every other station's
training matrix, and the whole ensemble had to be retrained from scratch (~30GB RAM, up to an
hour) for any change. Fitting one Random Forest per station instead means training cost grows
linearly with station count, each fit takes seconds, and stations can be added or drop out
independently. See `infrastructure/helm`'s comments and `internal/forest`'s package doc for more on
the trade-offs made.
