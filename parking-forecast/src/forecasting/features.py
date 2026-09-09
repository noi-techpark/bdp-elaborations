# SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Builds the fixed-size feature row the forest model is trained and
evaluated on, shared by train/main.py and predict/main.py. Unlike the old
pipeline, the feature count never grows with the number of stations (no
one-hot station index) or with time resolution (no one-hot hour column) —
this is what lets a single set of hyperparameters and a fast, independent
per-station fit scale to many more stations.
"""

import math
from dataclasses import dataclass
from datetime import datetime, timezone

from storage.reference import DayInfo

# Every feature row has exactly this many columns, in this order.
IDX_SIN_TIME = 0
IDX_COS_TIME = 1
IDX_SIN_DOW = 2
IDX_COS_DOW = 3
IDX_SIN_SEASON = 4
IDX_COS_SEASON = 5
IDX_IS_HOLIDAY = 6
IDX_IS_SCHOOL = 7
IDX_WEATHER = 8
IDX_LAG_NOW = 9
IDX_LAG_PREV_5M = 10
IDX_LAG_1H = 11
IDX_LAG_1D = 12
IDX_LAG_1W = 13
IDX_MEAN_7D = 14
IDX_HORIZON_MINUTES = 15
NUM_FEATURES = 16

STEP_SECONDS = 300  # matches the ODH parking occupancy sample period
LAG_1H = 12 * STEP_SECONDS
LAG_1D = 288 * STEP_SECONDS
LAG_1W = 2016 * STEP_SECONDS
MEAN_7D_SPAN = 7 * 24 * 60 * 60

# Horizons train/main.py generates labeled rows for; predict/main.py evaluates
# any horizon by varying IDX_HORIZON_MINUTES against a fixed anchor instead of
# rolling recursively (see predict/main.py's doc for why).
TRAINING_HORIZONS_MINUTES = [30, 60, 90, 120, 150, 180, 210, 240]


@dataclass
class Inputs:
    """occupancy and mean_7d are keyed by unix timestamp (UTC, 5-minute
    aligned); holidays/weather are keyed by ISO date (YYYY-MM-DD).
    """

    occupancy: dict[int, float]
    mean_7d: dict[int, float]
    holidays: dict[str, DayInfo]
    weather: dict[str, int]


def truncate_to_step(dt: datetime) -> datetime:
    """Rounds dt down to the nearest STEP_SECONDS grid line. ODH's raw feed
    isn't reliably grid-aligned, and every lookup here strides in fixed
    STEP_SECONDS steps, so an unaligned anchor would silently miss
    grid-aligned samples.
    """
    unix = int(dt.timestamp())
    return datetime.fromtimestamp(unix - (unix % STEP_SECONDS), tz=timezone.utc)


def _weekday_sunday0(dt: datetime) -> int:
    """Sunday=0 .. Saturday=6, matching Go's time.Weekday()."""
    return (dt.weekday() + 1) % 7


def build(target: datetime, anchor: datetime, inputs: Inputs) -> tuple[list[float], bool]:
    """Builds the feature row for predicting occupancy at target, anchored on
    the most recent known observation at anchor. Calendar features describe
    target (the point being forecast); lag/rolling-mean features describe
    anchor — occupancy near target's own timestamp can't be used without
    leaking the thing being predicted. ok is False when mandatory data isn't
    available yet.
    """
    target = target.astimezone(timezone.utc)
    anchor = anchor.astimezone(timezone.utc)
    unix = int(target.timestamp())
    anchor_unix = int(anchor.timestamp())

    x = [0.0] * NUM_FEATURES

    minute_of_day = target.hour * 60 + target.minute
    angle_day = 2 * math.pi * minute_of_day / 1440
    x[IDX_SIN_TIME] = math.sin(angle_day)
    x[IDX_COS_TIME] = math.cos(angle_day)

    angle_week = 2 * math.pi * _weekday_sunday0(target) / 7
    x[IDX_SIN_DOW] = math.sin(angle_week)
    x[IDX_COS_DOW] = math.cos(angle_week)

    angle_year = 2 * math.pi * (target.timetuple().tm_yday - 1) / 365.25
    x[IDX_SIN_SEASON] = math.sin(angle_year)
    x[IDX_COS_SEASON] = math.cos(angle_year)

    date_key = target.strftime("%Y-%m-%d")
    day = inputs.holidays.get(date_key)
    if day is None:
        return x, False
    x[IDX_IS_HOLIDAY] = float(day.is_holiday)
    x[IDX_IS_SCHOOL] = float(day.is_school)

    symbol = inputs.weather.get(date_key)
    if symbol is None:
        return x, False
    x[IDX_WEATHER] = float(symbol)

    occ = inputs.occupancy
    lag_now = occ.get(anchor_unix)
    lag_prev_5m = occ.get(anchor_unix - STEP_SECONDS)
    lag_1h = occ.get(anchor_unix - LAG_1H)
    lag_1d = occ.get(anchor_unix - LAG_1D)
    lag_1w = occ.get(anchor_unix - LAG_1W)
    if None in (lag_now, lag_prev_5m, lag_1h, lag_1d, lag_1w):
        return x, False
    x[IDX_LAG_NOW] = lag_now
    x[IDX_LAG_PREV_5M] = lag_prev_5m
    x[IDX_LAG_1H] = lag_1h
    x[IDX_LAG_1D] = lag_1d
    x[IDX_LAG_1W] = lag_1w

    mean_7d = inputs.mean_7d.get(anchor_unix)
    if mean_7d is None:
        return x, False
    x[IDX_MEAN_7D] = mean_7d

    x[IDX_HORIZON_MINUTES] = (unix - anchor_unix) / 60

    return x, True


def normalize(raw: dict[int, float], capacity: float) -> dict[int, float]:
    """Converts raw occupancy counts to ratios so lag/mean features are
    comparable across stations of different sizes. Unknown capacity (<= 0)
    passes values through unchanged.
    """
    out = {}
    for ts, v in raw.items():
        if v < 0:
            v = 0.0
        if capacity > 0:
            v /= capacity
        out[ts] = v
    return out


def denormalize(ratio: float, capacity: float) -> float:
    """Converts a model prediction back to occupancy-count units, clamped to
    [0, capacity] when capacity is known.
    """
    v = ratio
    if capacity > 0:
        v *= capacity
        if v > capacity:
            v = capacity
    if v < 0:
        v = 0.0
    return v


def rolling_mean_7d(occ: dict[int, float], from_ts: datetime, to_ts: datetime) -> dict[int, float]:
    """Mean of occ over the preceding 7 days ending at ts-5min — never looks
    at ts itself, so it can't leak the training target.
    """
    return _rolling_mean(occ, from_ts, to_ts, MEAN_7D_SPAN)


def _rolling_mean(occ: dict[int, float], from_ts: datetime, to_ts: datetime, span_seconds: int) -> dict[int, float]:
    ts = sorted(occ.keys())

    out: dict[int, float] = {}
    total = 0.0
    count = 0
    lo, hi = 0, 0  # window covers ts[lo:hi]

    from_unix = int(from_ts.timestamp())
    to_unix = int(to_ts.timestamp())

    cur = from_unix
    while cur <= to_unix:
        window_end = cur - STEP_SECONDS
        window_start = cur - span_seconds

        while hi < len(ts) and ts[hi] <= window_end:
            total += occ[ts[hi]]
            count += 1
            hi += 1
        while lo < hi and ts[lo] < window_start:
            total -= occ[ts[lo]]
            count -= 1
            lo += 1

        if count > 0:
            out[cur] = total / count

        cur += STEP_SECONDS

    return out
