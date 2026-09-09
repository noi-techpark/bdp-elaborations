# SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>
#
# SPDX-License-Identifier: CC0-1.0

FROM python:3.14-slim AS base

WORKDIR /app
COPY src/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Test stage ───────────────────────────────────────────────────────────────
FROM base AS test
COPY src/. .
ENV PYTHONPATH=/app
CMD ["python", "-m", "pytest", "tests/", "-v"]

# ── Production stage ─────────────────────────────────────────────────────────
FROM base AS build

COPY src/. .
ENV PYTHONPATH=/app

# main.py is the single entry point for every job (see main.py's own
# docstring). The default CMD runs the full local-dev pipeline; in
# production each job's k8s CronJob container instead sets its own command
# (see infrastructure/helm), e.g. ["python", "/app/main.py", "train"],
# which replaces this ENTRYPOINT+CMD pair entirely.
ENTRYPOINT ["python", "/app/main.py"]
CMD ["pipeline"]
