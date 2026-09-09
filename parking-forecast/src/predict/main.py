# SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Evaluates every station's forest directly, once per forecast step,
anchored on the same cutoff (the most recent real observation) each time,
then writes the legacy result.json.

This is deliberately not a recursive rollout: an earlier version fed each
step's own prediction back in as the next step's lag feature. A backtest
against production showed that compounding error, losing ground steadily
past ~90 minutes out. Evaluating every horizon directly from the same real
anchor (see features.build) avoids that: a mistake at 30 minutes can't
influence the prediction at 4 hours.
"""

import logging
from datetime import datetime, timedelta, timezone

from forecasting import features, forest, resultjson
from storage import db, models, occupancy, reference, stations
from util import logging_setup, settings

log = logging.getLogger("predict")

# accounts for ingest's cadence: stations whose last sample is older than
# this get an all-null forecast rather than a stale one.
PREDICT_SAFETY_MARGIN = timedelta(minutes=10)

HISTORY_BUFFER = timedelta(days=8)  # longest lookback any feature needs (lag1w)


def main() -> None:
    logging_setup.setup_logging("predict")
    conn = db.open_db(settings.DB_PATH)
    try:
        active_stations = stations.active_stations(conn)
        log.info("prediction run starting", extra={"stations": len(active_stations)})

        holiday_map = reference.all_holidays(conn)
        weather_map = reference.all_weather(conn)

        cutoff = features.truncate_to_step(datetime.now(timezone.utc) - PREDICT_SAFETY_MARGIN)
        horizon_steps = settings.HOURS_TO_PREDICT * 60 // (features.STEP_SECONDS // 60)
        from_ts = cutoff - HISTORY_BUFFER

        log.info("forecast window", extra={"cutoff": cutoff, "horizonSteps": horizon_steps})

        loaded_models = load_models(conn, active_stations)

        forecasts = [
            predict_station(
                conn,
                s,
                loaded_models.get(s.scode),
                holiday_map,
                weather_map,
                from_ts,
                cutoff,
                horizon_steps,
                settings.FOREST_LO_PERCENTILE,
                settings.FOREST_HI_PERCENTILE,
            )
            for s in active_stations
        ]

        try:
            resultjson.write_result_json(
                settings.RESULT_JSON_PATH,
                cutoff + timedelta(seconds=features.STEP_SECONDS),
                settings.HOURS_TO_PREDICT,
                settings.MODEL_VERSION,
                forecasts,
            )
            log.info("wrote legacy result.json", extra={"path": settings.RESULT_JSON_PATH})
        except Exception as e:
            log.error("writing legacy result.json failed: %s", e)

        log.info("prediction run complete")
    finally:
        conn.close()


def predict_station(
    conn,
    s,
    model,
    holiday_map: dict,
    weather_map: dict,
    from_ts: datetime,
    cutoff: datetime,
    horizon_steps: int,
    lo_pct: float,
    hi_pct: float,
) -> resultjson.StationForecast:
    """A None model or unloadable history yields an all-null forecast."""
    fc = resultjson.StationForecast(scode=s.scode)

    def null_forecast() -> resultjson.StationForecast:
        fc.points = [
            resultjson.Point(ts=cutoff + timedelta(seconds=step * features.STEP_SECONDS))
            for step in range(1, horizon_steps + 1)
        ]
        return fc

    if model is None:
        return null_forecast()

    try:
        raw_occ = occupancy.occupancy_map(conn, s.scode, from_ts, cutoff)
    except Exception as e:
        log.error("loading occupancy history failed", extra={"scode": s.scode, "err": str(e)})
        return null_forecast()

    occ = features.normalize(raw_occ, s.capacity)
    mean_7d = features.rolling_mean_7d(occ, cutoff, cutoff)

    inputs = features.Inputs(occupancy=occ, mean_7d=mean_7d, holidays=holiday_map, weather=weather_map)

    for step in range(1, horizon_steps + 1):
        ts = cutoff + timedelta(seconds=step * features.STEP_SECONDS)

        row, ok = features.build(ts, cutoff, inputs)
        if not ok:
            fc.points.append(resultjson.Point(ts=ts))
            continue

        mean_ratio, lo_ratio, hi_ratio = forest.predict_stats(model, row, lo_pct, hi_pct)

        capacity = s.capacity
        lo = features.denormalize(lo_ratio, capacity)
        mean = features.denormalize(mean_ratio, capacity)
        hi = features.denormalize(hi_ratio, capacity)
        fc.points.append(resultjson.Point(ts=ts, lo=lo, mean=mean, hi=hi))

    return fc


def load_models(conn, active_stations) -> dict:
    out = {}
    for s in active_stations:
        loaded = models.load_model(conn, s.scode)
        if loaded is None:
            continue
        blob, _trained_at = loaded
        try:
            out[s.scode] = forest.unmarshal(blob)
        except Exception as e:
            log.error("unmarshaling forest, skipping station", extra={"scode": s.scode, "err": str(e)})
    return out


if __name__ == "__main__":
    main()
