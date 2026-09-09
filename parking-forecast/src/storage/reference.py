# SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import sqlite3
from dataclasses import dataclass


@dataclass
class DayInfo:
    is_school: bool = False
    is_holiday: bool = False


def upsert_holidays(conn: sqlite3.Connection, by_date: dict[str, DayInfo]) -> None:
    with conn:
        conn.executemany(
            """
            INSERT INTO holidays (date, is_school, is_holiday) VALUES (?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET is_school = excluded.is_school, is_holiday = excluded.is_holiday
            """,
            [(date, int(info.is_school), int(info.is_holiday)) for date, info in by_date.items()],
        )


def all_holidays(conn: sqlite3.Connection) -> dict[str, DayInfo]:
    rows = conn.execute("SELECT date, is_school, is_holiday FROM holidays").fetchall()
    return {r[0]: DayInfo(is_school=bool(r[1]), is_holiday=bool(r[2])) for r in rows}


def upsert_weather(conn: sqlite3.Connection, by_date: dict[str, int]) -> None:
    with conn:
        conn.executemany(
            """
            INSERT INTO weather (date, symbol_value) VALUES (?, ?)
            ON CONFLICT(date) DO UPDATE SET symbol_value = excluded.symbol_value
            """,
            list(by_date.items()),
        )


def all_weather(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT date, symbol_value FROM weather").fetchall()
    return {r[0]: r[1] for r in rows}


def latest_weather_date(conn: sqlite3.Connection) -> str:
    """Empty string if there's no cached weather yet."""
    row = conn.execute("SELECT COALESCE(MAX(date), '') FROM weather").fetchone()
    return row[0]
