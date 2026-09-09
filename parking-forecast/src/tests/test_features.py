# SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import math
from datetime import datetime, timedelta, timezone

from forecasting import features
from storage.reference import DayInfo


def full_inputs(anchor: datetime) -> features.Inputs:
    unix = int(anchor.timestamp())
    return features.Inputs(
        occupancy={
            unix: 0.1,
            unix - features.STEP_SECONDS: 0.1,
            unix - features.LAG_1H: 0.1,
            unix - features.LAG_1D: 0.1,
            unix - features.LAG_1W: 0.1,
        },
        mean_7d={unix: 0.3},
        holidays={anchor.strftime("%Y-%m-%d"): DayInfo()},
        weather={anchor.strftime("%Y-%m-%d"): 1},
    )


def test_seasonal_feature_wraps_around_new_year():
    dec31 = datetime(2025, 12, 31, 12, 0, 0, tzinfo=timezone.utc)
    jan1 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    jul1 = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)

    x_dec31, ok = features.build(dec31, dec31, full_inputs(dec31))
    assert ok
    x_jan1, ok = features.build(jan1, jan1, full_inputs(jan1))
    assert ok
    x_jul1, ok = features.build(jul1, jul1, full_inputs(jul1))
    assert ok

    dist_new_year = math.hypot(
        x_dec31[features.IDX_SIN_SEASON] - x_jan1[features.IDX_SIN_SEASON],
        x_dec31[features.IDX_COS_SEASON] - x_jan1[features.IDX_COS_SEASON],
    )
    dist_half_year = math.hypot(
        x_dec31[features.IDX_SIN_SEASON] - x_jul1[features.IDX_SIN_SEASON],
        x_dec31[features.IDX_COS_SEASON] - x_jul1[features.IDX_COS_SEASON],
    )

    assert dist_new_year < dist_half_year
    assert dist_new_year <= 0.1


def test_rolling_mean_7d_excludes_current_point():
    base = datetime(2026, 1, 8, 12, 0, 0, tzinfo=timezone.utc)  # an arbitrary Thursday noon
    occ = {}
    t = base - timedelta(days=8)
    while t <= base:
        occ[int(t.timestamp())] = 0.5
        t += timedelta(seconds=features.STEP_SECONDS)
    occ[int(base.timestamp())] = 999  # must NOT leak into its own rolling mean

    out = features.rolling_mean_7d(occ, base - timedelta(hours=1), base)
    got = out.get(int(base.timestamp()))
    assert got is not None
    assert abs(got - 0.5) < 1e-9


def test_rolling_mean_7d_missing_when_no_history():
    base = datetime(2026, 1, 8, 12, 0, 0, tzinfo=timezone.utc)
    occ = {int(base.timestamp()): 1.0}
    out = features.rolling_mean_7d(occ, base, base)
    assert int(base.timestamp()) not in out


def test_build_requires_all_mandatory_inputs():
    anchor = datetime(2026, 1, 8, 8, 5, 0, tzinfo=timezone.utc)
    full = full_inputs(anchor)

    _, ok = features.build(anchor, anchor, full)
    assert ok

    missing_lag = features.Inputs(
        occupancy={int(anchor.timestamp()): 0.1},
        mean_7d=full.mean_7d,
        holidays=full.holidays,
        weather=full.weather,
    )
    _, ok = features.build(anchor, anchor, missing_lag)
    assert not ok

    missing_weather = features.Inputs(
        occupancy=full.occupancy, mean_7d=full.mean_7d, holidays=full.holidays, weather={}
    )
    _, ok = features.build(anchor, anchor, missing_weather)
    assert not ok


def test_build_direct_horizon_uses_anchor_lags_and_target_calendar():
    anchor = datetime(2026, 1, 8, 8, 5, 0, tzinfo=timezone.utc)  # a Thursday
    full = full_inputs(anchor)
    target = anchor + timedelta(hours=2)

    row, ok = features.build(target, anchor, full)
    assert ok
    assert row[features.IDX_HORIZON_MINUTES] == 120
    assert row[features.IDX_LAG_NOW] == 0.1
    assert row[features.IDX_LAG_PREV_5M] == 0.1

    next_day = anchor + timedelta(hours=24)
    full.holidays[next_day.strftime("%Y-%m-%d")] = DayInfo()
    full.weather[next_day.strftime("%Y-%m-%d")] = 1
    row_next_day, ok = features.build(next_day, anchor, full)
    assert ok
    assert not (
        row_next_day[features.IDX_SIN_DOW] == row[features.IDX_SIN_DOW]
        and row_next_day[features.IDX_COS_DOW] == row[features.IDX_COS_DOW]
    )
