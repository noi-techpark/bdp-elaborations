# SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import sqlite3
from datetime import datetime, timezone


def save_model(conn: sqlite3.Connection, scode: str, blob: bytes, trained_at: datetime, train_rows: int) -> None:
    """Replaces whatever was trained before — one current model per station."""
    with conn:
        conn.execute(
            """
            INSERT INTO models (scode, trained_at, train_rows, forest_blob) VALUES (?, ?, ?, ?)
            ON CONFLICT(scode) DO UPDATE SET trained_at = excluded.trained_at, train_rows = excluded.train_rows, forest_blob = excluded.forest_blob
            """,
            (scode, int(trained_at.timestamp()), train_rows, blob),
        )


def load_model(conn: sqlite3.Connection, scode: str) -> tuple[bytes, datetime] | None:
    row = conn.execute("SELECT forest_blob, trained_at FROM models WHERE scode = ?", (scode,)).fetchone()
    if row is None:
        return None
    return row[0], datetime.fromtimestamp(row[1], tz=timezone.utc)


def stations_with_models(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT scode FROM models").fetchall()
    return {r[0] for r in rows}
