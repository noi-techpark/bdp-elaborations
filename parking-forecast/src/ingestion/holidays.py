# SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Ports data-holidays-get.py: it derives per-day is_school/is_holiday flags
from the Tourism Open Data Hub's school- and public-holiday Events, and
caches them via storage.reference instead of data-holidays/holidays.csv.
"""

import sqlite3
from datetime import date, datetime, timedelta

import requests

from storage import reference

PAGE_SIZE = 500


def _fetch_event_dates(base_url: str, tag: str) -> set[str]:
    resp = requests.get(
        f"{base_url}/Event",
        params={"rawfilter": f"and(like(Tags,'{tag}'))", "pagesize": str(PAGE_SIZE)},
    )
    resp.raise_for_status()
    items = resp.json().get("Items", [])

    dates: set[str] = set()
    for item in items:
        begin = _parse_event_date(item.get("DateBegin", ""))
        end = _parse_event_date(item.get("DateEnd", ""))
        if begin is None or end is None:
            continue
        d = begin
        while d <= end:
            dates.add(d.isoformat())
            d += timedelta(days=1)
    return dates


def _parse_event_date(s: str) -> date | None:
    if len(s) < 10:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def fetch_and_cache(base_url: str, conn: sqlite3.Connection) -> None:
    """Always refetches the full event set — school/public holiday calendars
    are small and published years ahead, so there's no meaningful
    incremental fetch here, unlike occupancy or weather.
    """
    school_dates = _fetch_event_dates(base_url, "school holiday")
    public_dates = _fetch_event_dates(base_url, "public holiday")

    all_dates = school_dates | public_dates
    if not all_dates:
        return

    min_date = min(date.fromisoformat(d) for d in all_dates)
    max_date = max(date.fromisoformat(d) for d in all_dates)

    by_date: dict[str, reference.DayInfo] = {}
    d = min_date
    while d <= max_date:
        key = d.isoformat()
        is_school_holiday = key in school_dates
        is_public_holiday = key in public_dates
        is_weekend = d.weekday() >= 5  # Saturday=5, Sunday=6

        by_date[key] = reference.DayInfo(
            is_school=not (is_weekend or is_school_holiday or is_public_holiday),
            is_holiday=is_public_holiday or is_weekend,
        )
        d += timedelta(days=1)

    reference.upsert_holidays(conn, by_date)
