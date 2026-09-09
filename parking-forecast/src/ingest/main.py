# SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Refreshes the local SQLite cache: station metadata, holiday and weather
reference data, and — incrementally, in batches of stationBatchSize
stations per request — occupancy history. It replaces
data-raw-get.js/data-raw-get-diff.js/data-holidays-get.*/data-meteo-get.sh.
Scheduled frequently (e.g. every 15 minutes) as its own k8s CronJob.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ingestion import holidays, odh_client, weather
from storage import db, occupancy, stations
from util import logging_setup, settings

log = logging.getLogger("ingest")

# "dawn of time" for stations we've never cached anything for yet.
MIN_HISTORY_START = datetime(2022, 1, 1, tzinfo=timezone.utc)

FETCH_CONCURRENCY = 8
MAX_BATCH_STATIONS = 200
# 1000-char safety margin mirrors opendatahub-go-sdk/elab's own bucketing
# for a station code filter.
MAX_BATCH_URL_CHARS = 1000


@dataclass
class PendingStation:
    station: odh_client.StationInfo
    from_ts: datetime
    to_ts: datetime


def main() -> None:
    logging_setup.setup_logging("ingest")
    conn = db.open_db(settings.DB_PATH)
    try:
        client = odh_client.Client(
            base_url=settings.TS_API_BASE_URL,
            token_url=settings.ODH_TOKEN_URL,
            referer=settings.TS_API_REFERER,
            client_id=settings.ODH_CLIENT_ID,
            client_secret=settings.ODH_CLIENT_SECRET,
            station_types=settings.STATION_TYPES,
            occupancy_type=settings.OCCUPANCY_DATA_TYPE,
            occupancy_period=settings.OCCUPANCY_PERIOD,
        )

        log.info("fetching station metadata")
        odh_stations = client.fetch_stations()
        log.info("fetched stations", extra={"count": len(odh_stations)})

        store_stations = [
            stations.Station(
                scode=s.scode, name=s.name, station_type=s.station_type, lat=s.lat, lon=s.lon, capacity=s.capacity, active=True
            )
            for s in odh_stations
        ]
        stations.upsert_stations(conn, store_stations)

        log.info("refreshing holidays cache")
        try:
            holidays.fetch_and_cache(settings.TOURISM_API_BASE_URL, conn)
        except Exception as e:
            log.error("refreshing holidays failed, keeping previous cache: %s", e)

        log.info("refreshing weather cache")
        try:
            weather.fetch_and_cache(settings.TOURISM_API_BASE_URL, conn)
        except Exception as e:
            log.error("refreshing weather failed, keeping previous cache: %s", e)

        ingest_occupancy(client, conn, odh_stations)

        retention_cutoff = datetime.now(timezone.utc) - timedelta(days=settings.OCCUPANCY_RETENTION_DAYS)
        try:
            purged = occupancy.purge_occupancy_before(conn, retention_cutoff)
            if purged > 0:
                log.info("purged old occupancy history", extra={"cutoff": retention_cutoff, "rowsRemoved": purged})
        except Exception as e:
            log.error("purging old occupancy history failed: %s", e)

        log.info("ingest complete")
    finally:
        conn.close()


def ingest_occupancy(client: odh_client.Client, conn, odh_stations: list[odh_client.StationInfo]) -> None:
    by_type: dict[str, list[PendingStation]] = {}

    for s in odh_stations:
        if not s.has_occupancy_ts:
            continue  # ODH has no data for this station at all yet

        from_ts = MIN_HISTORY_START
        cursor = occupancy.last_occupancy_ts(conn, s.scode)
        if cursor is not None:
            from_ts = cursor + timedelta(seconds=1)

        to_ts = s.last_occupancy_ts + timedelta(milliseconds=1)  # half-open range
        if not to_ts > from_ts:
            continue  # already caught up

        by_type.setdefault(s.station_type, []).append(PendingStation(station=s, from_ts=from_ts, to_ts=to_ts))

    with ThreadPoolExecutor(max_workers=FETCH_CONCURRENCY) as pool:
        futures = []
        for station_type, pending in by_type.items():
            # Sorting by catch-up start clusters already-caught-up stations
            # into cheap, narrow-range batches instead of dragging them back
            # to 2022 alongside a brand-new station.
            pending.sort(key=lambda p: p.from_ts)

            for batch in chunk_by_url_length(pending):
                futures.append(pool.submit(_fetch_batch, client, station_type, batch))

        for future in as_completed(futures):
            station_type, batch, measurements, error = future.result()
            if error is not None:
                log.error(
                    "fetching occupancy history batch failed",
                    extra={"stationType": station_type, "stations": len(batch), "err": str(error)},
                )
                continue
            _cache_batch(conn, batch, measurements)


def _fetch_batch(client: odh_client.Client, station_type: str, batch: list[PendingStation]):
    from_ts = min(p.from_ts for p in batch)
    to_ts = max(p.to_ts for p in batch)
    scodes = [p.station.scode for p in batch]
    try:
        measurements = client.fetch_occupancy_history(station_type, scodes, from_ts, to_ts)
        return station_type, batch, measurements, None
    except Exception as e:
        return station_type, batch, None, e


def _cache_batch(conn, batch: list[PendingStation], measurements: list[odh_client.Measurement]) -> None:
    by_station: dict[str, list[occupancy.OccPoint]] = {}
    for m in measurements:
        by_station.setdefault(m.station_code, []).append(occupancy.OccPoint(ts=m.timestamp, value=m.value))

    for p in batch:
        # The batch's shared "from" can be earlier than this particular
        # station's own cursor (it's the min across the batch); drop
        # anything at or before its cursor to avoid redundant writes.
        points = [pt for pt in by_station.get(p.station.scode, []) if pt.ts >= p.from_ts]
        try:
            occupancy.insert_occupancy(conn, p.station.scode, points)
        except Exception as e:
            log.error("caching occupancy history failed", extra={"scode": p.station.scode, "err": str(e)})


def chunk_by_url_length(pending: list[PendingStation]) -> list[list[PendingStation]]:
    """Splits pending into batches that respect both MAX_BATCH_STATIONS and
    MAX_BATCH_URL_CHARS.
    """
    chunks: list[list[PendingStation]] = []
    current: list[PendingStation] = []
    url_chars = 0

    for p in pending:
        code_len = len(p.station.scode) + 3  # quotes + comma/escaping overhead, same estimate elab uses
        if current and (len(current) >= MAX_BATCH_STATIONS or url_chars + code_len > MAX_BATCH_URL_CHARS):
            chunks.append(current)
            current = []
            url_chars = 0
        current.append(p)
        url_chars += code_len
    if current:
        chunks.append(current)
    return chunks


if __name__ == "__main__":
    main()
