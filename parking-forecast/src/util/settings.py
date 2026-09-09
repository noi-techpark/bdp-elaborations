# SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Environment configuration shared by the ingest, train and predict jobs."""

import os

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Open Data Hub time series API ("ninja") — occupancy history
TS_API_BASE_URL = os.getenv("TS_API_BASE_URL", "https://mobility.api.opendatahub.com/v2")
TS_API_REFERER = os.getenv("TS_API_REFERER", "el-parking-forecast")
ODH_TOKEN_URL = os.getenv("ODH_TOKEN_URL", "")
ODH_CLIENT_ID = os.getenv("ODH_CLIENT_ID", "")
ODH_CLIENT_SECRET = os.getenv("ODH_CLIENT_SECRET", "")
STATION_TYPES = [s for s in os.getenv("STATION_TYPES", "ParkingStation,ParkingSensor").split(",") if s]
OCCUPANCY_DATA_TYPE = os.getenv("OCCUPANCY_DATA_TYPE", "occupied")
OCCUPANCY_PERIOD = int(os.getenv("OCCUPANCY_PERIOD", "300"))

# Tourism Open Data Hub API — weather + school/public holiday events
TOURISM_API_BASE_URL = os.getenv("TOURISM_API_BASE_URL", "https://tourism.api.opendatahub.com/v1")

# Local SQLite cache: occupancy/weather/holiday history, station metadata
# and fitted per-station forests. Mounted on a PVC in production.
DB_PATH = os.getenv("DB_PATH", "data/parking.db")

# 400 days = a bit over 13 months, enough for a full annual seasonal cycle
# (see features.IDX_SIN_SEASON) — keeps the cache bounded forever instead of
# growing with every station-year ingested.
OCCUPANCY_RETENTION_DAYS = int(os.getenv("OCCUPANCY_RETENTION_DAYS", "400"))

# Model
FOREST_TREES = int(os.getenv("FOREST_TREES", "60"))
FOREST_MAX_DEPTH = int(os.getenv("FOREST_MAX_DEPTH", "8"))
FOREST_MIN_LEAF_SAMPLES = int(os.getenv("FOREST_MIN_LEAF_SAMPLES", "20"))
FOREST_ROW_SUBSAMPLE = float(os.getenv("FOREST_ROW_SUBSAMPLE", "0.8"))
FOREST_FEATURE_SUBSAMPLE = float(os.getenv("FOREST_FEATURE_SUBSAMPLE", "0.7"))
MIN_TRAIN_ROWS = int(os.getenv("MIN_TRAIN_ROWS", "500"))
MODEL_VERSION = os.getenv("MODEL_VERSION", "2.0")
FOREST_LO_PERCENTILE = float(os.getenv("FOREST_LO_PERCENTILE", "0.1"))
FOREST_HI_PERCENTILE = float(os.getenv("FOREST_HI_PERCENTILE", "0.9"))

# Prediction
HOURS_TO_PREDICT = int(os.getenv("HOURS_TO_PREDICT", "48"))
RESULT_JSON_PATH = os.getenv("RESULT_JSON_PATH", "result/result.json")
