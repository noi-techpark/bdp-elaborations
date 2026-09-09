# SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""JSON structured logging. Every key passed via `extra={...}` in a log call
ends up as its own field in the emitted JSON line — plain %-style formatting
(logging.basicConfig) would silently drop those fields instead.
"""

import logging.config

from util.settings import LOG_LEVEL


def setup_logging(service_name: str) -> None:
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "json": {
                    "()": "pythonjsonlogger.json.JsonFormatter",
                    "fmt": "%(asctime)s %(name)s %(levelname)s %(message)s",
                    "rename_fields": {"asctime": "timestamp", "levelname": "level"},
                    "static_fields": {"service": service_name},
                }
            },
            "handlers": {
                "stdout": {
                    "class": "logging.StreamHandler",
                    "formatter": "json",
                    "stream": "ext://sys.stdout",
                }
            },
            "root": {
                "level": LOG_LEVEL,
                "handlers": ["stdout"],
            },
            "loggers": {
                "urllib3": {"level": "WARNING", "propagate": True},
                "requests": {"level": "WARNING", "propagate": True},
            },
        }
    )
