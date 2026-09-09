# SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Ports data-meteo-get.sh: it pulls the daily weather symbol forecast
(station id 3 of the Tourism Open Data Hub's WeatherHistory feed) and caches
it via storage.reference instead of data-meteo/meteo.csv.
"""

import sqlite3

import requests

from storage import reference

# station id 3 is the "province-wide" forecast used by the old pipeline.
STATION_ID = 3

DEFAULT_FROM = "2021-12-31"  # cold-cache starting point

# A cold-cache fetch from DEFAULT_FROM covers ~1600 rows; requesting them all
# in one page via pagesize=0 makes the API 500 once the result set is this
# large, so this paginates instead.
PAGE_SIZE = 200


def _weather_code_to_symbol(code: str) -> int | None:
    """Maps a single a-z letter code to the 0-25 ordinal the model expects."""
    if not code:
        return None
    c = code[0]
    if c < "a" or c > "z":
        return None
    return ord(c) - ord("a")


def fetch_and_cache(base_url: str, conn: sqlite3.Connection) -> None:
    """Fetches weather symbols from the given date onward (or the latest
    cached date, whichever is more recent) and upserts them into conn.
    """
    from_date = reference.latest_weather_date(conn) or DEFAULT_FROM

    by_date: dict[str, int] = {}
    page = 1
    while True:
        resp = requests.get(
            f"{base_url}/WeatherHistory",
            params={
                "rawsort": "_Meta.LastUpdate",
                "fields": "Weather.en.Stationdata",
                "pagesize": str(PAGE_SIZE),
                "pagenumber": str(page),
                "datefrom": from_date,
            },
        )
        resp.raise_for_status()
        body = resp.json()

        for item in body.get("Items", []):
            for sd in item.get("Weather.en.Stationdata", []):
                if sd.get("Id") != STATION_ID:
                    continue
                date_str = sd.get("date", "")
                if len(date_str) >= 10:
                    date_str = date_str[:10]
                symbol = _weather_code_to_symbol(sd.get("WeatherCode", ""))
                if symbol is None:
                    continue
                # a "today" and "tomorrow" prediction can cover the same
                # day; last one in response order wins.
                by_date[date_str] = symbol

        total_pages = body.get("TotalPages", 1)
        if page >= total_pages:
            break
        page += 1

    if not by_date:
        return
    reference.upsert_weather(conn, by_date)
