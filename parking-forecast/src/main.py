# SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Single entry point for every parking-forecast job: `python main.py
<ingest|train|predict|pipeline>`. In production each job still runs as its
own Kubernetes CronJob container (see infrastructure/helm); `pipeline` is a
local-dev convenience — see docker-compose.yml.
"""

import argparse
import sys

import ingest.main
import predict.main
import train.main

JOBS = {
    "ingest": ingest.main.main,
    "train": train.main.main,
    "predict": predict.main.main,
}


def run_pipeline() -> None:
    for job in ("ingest", "train", "predict"):
        JOBS[job]()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="parking-forecast")
    parser.add_argument("job", choices=[*JOBS, "pipeline"])
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.job == "pipeline":
        run_pipeline()
    else:
        JOBS[args.job]()


if __name__ == "__main__":
    main()
