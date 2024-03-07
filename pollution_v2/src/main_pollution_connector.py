# SPDX-FileCopyrightText: NOI Techpark <digital@noi.bz.it>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import absolute_import, annotations

import argparse
import logging.config

import dateutil.parser
import sentry_sdk

from common.logging import get_logging_configuration

import logging
from datetime import datetime
from typing import Optional

from redis.client import Redis

from pollution_connector.cache.computation_checkpoint import ComputationCheckpointCache
from common.connector.collector import ConnectorCollector
from common.data_model.common import Provenance
from common.settings import DEFAULT_TIMEZONE, ODH_MINIMUM_STARTING_DATE, PROVENANCE_ID, PROVENANCE_LINEAGE, \
    PROVENANCE_NAME, PROVENANCE_VERSION, COMPUTATION_CHECKPOINT_REDIS_HOST, \
    COMPUTATION_CHECKPOINT_REDIS_PORT, COMPUTATION_CHECKPOINT_REDIS_DB, SENTRY_SAMPLE_RATE
from pollution_connector.manager.pollution_computation import PollutionComputationManager

logging.config.dictConfig(get_logging_configuration("main_pollution_connector"))
logger = logging.getLogger("main_pollution_connector")

sentry_sdk.init(
    traces_sample_rate=SENTRY_SAMPLE_RATE,
    integrations=[]
)


def compute_pollution_data(min_from_date: Optional[datetime] = None,
                           max_to_date: Optional[datetime] = None
                           ) -> None:
    """
    Start the computation of a batch of pollution data measures. As starting date for the batch is used the latest
    pollution measure available on the ODH, if no pollution measures are available min_from_date is used.

    :param min_from_date: Optional, if set traffic measures before this date are discarded if no pollution measures are available.
                          If not specified, the default will be taken from the environmental variable `ODH_MINIMUM_STARTING_DATE`.
    :param max_to_date: Optional, if set the traffic measure after this date are discarded.
                        If not specified, the default will be the current datetime.
    """
    if min_from_date is None:
        min_from_date = ODH_MINIMUM_STARTING_DATE

    if max_to_date is None:
        max_to_date = datetime.now(tz=DEFAULT_TIMEZONE)

    checkpoint_cache = None
    if COMPUTATION_CHECKPOINT_REDIS_HOST:
        logger.info("Enabled checkpoint cache")
        checkpoint_cache = ComputationCheckpointCache(Redis(host=COMPUTATION_CHECKPOINT_REDIS_HOST, port=COMPUTATION_CHECKPOINT_REDIS_PORT, db=COMPUTATION_CHECKPOINT_REDIS_DB))
    else:
        logger.info("Checkpoint cache disabled")

    collector_connector = ConnectorCollector.build_from_env()
    provenance = Provenance(PROVENANCE_ID, PROVENANCE_LINEAGE, PROVENANCE_NAME, PROVENANCE_VERSION)
    manager = PollutionComputationManager(collector_connector, provenance, checkpoint_cache)
    manager.run_computation_and_upload_results(min_from_date, max_to_date)


if __name__ == "__main__":

    arg_parser = argparse.ArgumentParser(description="Manually run a pollution (v2) computation")
    arg_parser.add_argument("-f", "--from-date", type=str, required=False,
                            help="The starting date[time] in isoformat (up to one second level of precision, milliseconds for the from date field are not supported in ODH) for downloading data from ODH if no pollution measures are available")

    arg_parser.add_argument("-t", "--to-date", type=str, required=False,
                            help="The end date[time] in isoformat for downloading the traffic measures. If not specified, the default will be the current datetime")

    arg_parser.add_argument("--run-async", action="store_true", help="If set it run the task in the celery cluster")
    args = arg_parser.parse_args()

    if args.from_date:
        from_date = dateutil.parser.parse(args.from_date)
        if from_date.tzinfo is None:
            from_date = DEFAULT_TIMEZONE.localize(from_date)
        if from_date.microsecond:
            from_date = from_date.replace(microsecond=0)
    else:
        from_date = None

    if args.to_date:
        to_date = dateutil.parser.parse(args.to_date)
        if to_date.tzinfo is None:
            to_date = DEFAULT_TIMEZONE.localize(to_date)
    else:
        to_date = None

    compute_pollution_data(min_from_date=from_date, max_to_date=to_date)
    '''if args.run_async:
        task: AsyncResult = compute_pollution_data.delay(min_from_date=from_date, max_to_date=to_date)
        logger.info(f"Scheduled async pollution computation. Task ID: [{task.task_id}]")
    else:
        logger.info("Staring pollution computation")
        compute_pollution_data(min_from_date=from_date, max_to_date=to_date)'''
