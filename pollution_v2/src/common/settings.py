# SPDX-FileCopyrightText: NOI Techpark <digital@noi.bz.it>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import os

import dateutil.parser
import pytz
from airflow.models import Variable

# Pollution task
POLLUTION_TASK_SCHEDULING_MINUTE = os.getenv("POLLUTION_TASK_SCHEDULING_MINUTE", "*/10")
POLLUTION_TASK_SCHEDULING_HOUR = os.getenv("POLLUTION_TASK_SCHEDULING_HOUR", "*")

# Sentry
SENTRY_SAMPLE_RATE = float(os.getenv("SENTRY_SAMPLE_RATE", 1.0))

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_LEVEL_LIBS = os.getenv("LOG_LEVEL_LIBS", "DEBUG")
LOGS_DIR = os.getenv("LOGS_DIR", "")

# Open Data Hub
ODH_BASE_READER_URL = Variable.get("ODH_BASE_READER_URL")
ODH_BASE_WRITER_URL = Variable.get("ODH_BASE_WRITER_URL")
ODH_AUTHENTICATION_URL = Variable.get("ODH_AUTHENTICATION_URL")
ODH_USERNAME = Variable.get("ODH_USERNAME")
ODH_PASSWORD = Variable.get("ODH_PASSWORD")
ODH_CLIENT_ID = Variable.get("ODH_CLIENT_ID")
ODH_CLIENT_SECRET = Variable.get("ODH_CLIENT_SECRET")
ODH_GRANT_TYPE = Variable.get("ODH_GRANT_TYPE", "password").split(";")
ODH_PAGINATION_SIZE = int(Variable.get("ODH_PAGINATION_SIZE", 200))
ODH_MAX_POST_BATCH_SIZE = int(Variable.get("ODH_MAX_POST_BATCH_SIZE")) if Variable.get("ODH_MAX_POST_BATCH_SIZE") else None
ODH_COMPUTATION_BATCH_SIZE = int(Variable.get("ODH_COMPUTATION_BATCH_SIZE", 30))
ODH_MINIMUM_STARTING_DATE = dateutil.parser.parse(Variable.get("ODH_MINIMUM_STARTING_DATE", "2018-01-01"))
DAG_POLLUTION_EXECUTION_CRONTAB = Variable.get("DAG_POLLUTION_EXECUTION_CRONTAB", "0 0 * * *")
DAG_VALIDATION_EXECUTION_CRONTAB = Variable.get("DAG_VALIDATION_EXECUTION_CRONTAB", "0 0 * * *")
DAG_POLLUTION_TRIGGER_DAG_HOURS_SPAN = int(Variable.get("DAG_POLLUTION_TRIGGER_DAG_HOURS_SPAN", 24))

# General
DEFAULT_TIMEZONE = pytz.timezone(os.getenv("DEFAULT_TIMEZONE", "Europe/Rome"))

# Requests management
REQUESTS_TIMEOUT = float(os.getenv("REQUESTS_TIMEOUT", 300))
REQUESTS_MAX_RETRIES = int(os.getenv("REQUESTS_MAX_RETRIES", 1))
REQUESTS_SLEEP_TIME = float(os.getenv("REQUESTS_SLEEP_TIME", 0))
REQUESTS_RETRY_SLEEP_TIME = float(os.getenv("REQUESTS_RETRY_SLEEP_TIME", 30))

# Provenance
PROVENANCE_ID = os.getenv("PROVENANCE_ID")
PROVENANCE_LINEAGE = os.getenv("PROVENANCE_LINEAGE", "u-hopper")
PROVENANCE_NAME = os.getenv("PROVENANCE_NAME", "a22-pollutant-elaboration")
PROVENANCE_VERSION = os.getenv("PROVENANCE_VERSION", "0.1.0")

COMPUTATION_CHECKPOINT_REDIS_HOST = Variable.get("COMPUTATION_CHECKPOINT_REDIS_HOST", None)
COMPUTATION_CHECKPOINT_REDIS_PORT = int(Variable.get("COMPUTATION_CHECKPOINT_REDIS_PORT", 6379))
COMPUTATION_CHECKPOINT_REDIS_DB = int(Variable.get("COMPUTATION_CHECKPOINT_REDIS_DB", 0))
