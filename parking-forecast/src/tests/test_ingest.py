# SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from datetime import datetime, timezone

from ingestion.odh_client import StationInfo
from ingest.main import MAX_BATCH_STATIONS, MAX_BATCH_URL_CHARS, PendingStation, chunk_by_url_length

_now = datetime.now(timezone.utc)


def _pending(scode: str) -> PendingStation:
    return PendingStation(station=StationInfo(scode=scode, name="", station_type="", lat=0, lon=0, capacity=1), from_ts=_now, to_ts=_now)


def test_chunk_by_url_length_respects_both_bounds():
    # short codes: only max_batch_stations should kick in
    pending = [_pending(str(i)) for i in range(MAX_BATCH_STATIONS * 2 + 7)]
    chunks = chunk_by_url_length(pending)

    total = 0
    for c in chunks:
        assert len(c) <= MAX_BATCH_STATIONS
        total += len(c)
    assert total == len(pending)
    assert len(chunks) == 3  # 2 full + remainder


def test_chunk_by_url_length_respects_char_budget():
    # long codes: URL length should kick in well before max_batch_stations
    long_code = "TRENTO:some-quite-long-station-code-here"
    pending = [_pending(long_code) for _ in range(100)]
    chunks = chunk_by_url_length(pending)

    for c in chunks:
        url_chars = sum(len(p.station.scode) + 3 for p in c)
        assert url_chars <= MAX_BATCH_URL_CHARS
    assert len(chunks) >= 2


def test_chunk_by_url_length_empty():
    assert chunk_by_url_length([]) == []
