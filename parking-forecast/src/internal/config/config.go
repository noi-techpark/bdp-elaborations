// SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>
//
// SPDX-License-Identifier: AGPL-3.0-or-later

// Package config holds the environment configuration shared by the
// ingest, train and predict jobs.
package config

// Env is processed via envconfig (see github.com/kelseyhightower/envconfig)
// by ms.InitWithEnv in each cmd's main().
type Env struct {
	// Open Data Hub time series API ("ninja") — occupancy history
	TsApiBaseUrl    string   `envconfig:"TS_API_BASE_URL" default:"https://mobility.api.opendatahub.com/v2"`
	TsApiReferer    string   `envconfig:"TS_API_REFERER" default:"el-parking-forecast"`
	OdhTokenUrl     string   `envconfig:"ODH_TOKEN_URL"`
	OdhClientId     string   `envconfig:"ODH_CLIENT_ID"`
	OdhClientSecret string   `envconfig:"ODH_CLIENT_SECRET"`
	StationTypes    []string `envconfig:"STATION_TYPES" default:"ParkingStation,ParkingSensor"`
	OccupancyType   string   `envconfig:"OCCUPANCY_DATA_TYPE" default:"occupied"`
	OccupancyPeriod uint64   `envconfig:"OCCUPANCY_PERIOD" default:"300"`

	// Tourism Open Data Hub API — weather + school/public holiday events
	TourismApiBaseUrl string `envconfig:"TOURISM_API_BASE_URL" default:"https://tourism.api.opendatahub.com/v1"`

	// Local SQLite cache: occupancy/weather/holiday history, station
	// metadata and fitted per-station forests. Mounted on a PVC in production.
	DbPath string `envconfig:"DB_PATH" default:"data/parking.db"`

	// How much raw occupancy history ingest keeps before purging it (see
	// store.PurgeOccupancyBefore). 400 days = a bit over 13 months: enough
	// for the model to see a full annual seasonal cycle (see
	// features.IdxSinSeason) plus a buffer for the lag/rolling-window
	// features that need some history before the window they cover. This is
	// what keeps the cache — and nightly training cost — bounded forever,
	// instead of growing with every station-year ingested.
	OccupancyRetentionDays int `envconfig:"OCCUPANCY_RETENTION_DAYS" default:"400"`

	// Model
	ForestTrees            int     `envconfig:"FOREST_TREES" default:"60"`
	ForestMaxDepth         int     `envconfig:"FOREST_MAX_DEPTH" default:"8"`
	ForestMinLeafSamples   int     `envconfig:"FOREST_MIN_LEAF_SAMPLES" default:"20"`
	ForestRowSubsample     float64 `envconfig:"FOREST_ROW_SUBSAMPLE" default:"0.8"`
	ForestFeatureSubsample float64 `envconfig:"FOREST_FEATURE_SUBSAMPLE" default:"0.7"`
	MinTrainRows           int     `envconfig:"MIN_TRAIN_ROWS" default:"500"`
	ModelVersion           string  `envconfig:"MODEL_VERSION" default:"2.0"`
	ForestLoPercentile     float64 `envconfig:"FOREST_LO_PERCENTILE" default:"0.1"`
	ForestHiPercentile     float64 `envconfig:"FOREST_HI_PERCENTILE" default:"0.9"`

	// Prediction
	HoursToPredict int    `envconfig:"HOURS_TO_PREDICT" default:"48"`
	ResultJsonPath string `envconfig:"RESULT_JSON_PATH" default:"result/result.json"`
}
