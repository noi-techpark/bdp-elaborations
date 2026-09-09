# SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Fits one Random Forest per active station from the cached
occupancy/holiday/weather history and persists it to SQLite. Every training
row is "given what was known as of some anchor time, what was the occupancy
H minutes later," for a spread of H (features.TRAINING_HORIZONS_MINUTES) —
predict/main.py then evaluates any horizon directly from a fixed anchor,
with no recursive rollout.

Stations are trained sequentially: each forest's own fit already
parallelizes across every core via scikit-learn/joblib (n_jobs=-1), so
there's nothing to gain from also parallelizing across stations.
"""

import logging
from dataclasses import replace
from datetime import datetime, timezone

from forecasting import features, forest
from storage import db, models, occupancy, reference, stations
from util import logging_setup, settings

log = logging.getLogger("train")


def main() -> None:
    logging_setup.setup_logging("train")
    conn = db.open_db(settings.DB_PATH)
    try:
        active_stations = stations.active_stations(conn)
        log.info("training run starting", extra={"stations": len(active_stations)})

        holiday_map = reference.all_holidays(conn)
        weather_map = reference.all_weather(conn)

        forest_cfg = forest.Config(
            num_trees=settings.FOREST_TREES,
            max_depth=settings.FOREST_MAX_DEPTH,
            min_leaf_samples=settings.FOREST_MIN_LEAF_SAMPLES,
            row_subsample=settings.FOREST_ROW_SUBSAMPLE,
            feature_subsample=settings.FOREST_FEATURE_SUBSAMPLE,
        )

        now = features.truncate_to_step(datetime.now(timezone.utc))

        trained, skipped, failed = 0, 0, 0
        for i, s in enumerate(active_stations):
            cfg = replace(forest_cfg, seed=int(now.timestamp()) + i)
            try:
                rows = train_station(conn, s, holiday_map, weather_map, now, cfg, settings.MIN_TRAIN_ROWS)
            except Exception as e:
                failed += 1
                log.error("training station failed", extra={"scode": s.scode, "err": str(e)})
                continue

            if rows < settings.MIN_TRAIN_ROWS:
                skipped += 1
                log.warning(
                    "skipping station, not enough training data yet",
                    extra={"scode": s.scode, "rows": rows, "minRows": settings.MIN_TRAIN_ROWS},
                )
            else:
                trained += 1
                log.info("trained station", extra={"scode": s.scode, "rows": rows})

        log.info(
            "training run complete",
            extra={"trained": trained, "skipped": skipped, "failed": failed, "total": len(active_stations)},
        )
    finally:
        conn.close()


def train_station(conn, s, holiday_map, weather_map, now: datetime, forest_cfg: forest.Config, min_rows: int) -> int:
    """Returns the row count even below min_rows, so the caller can log why
    a station was skipped.
    """
    from_ts = occupancy.earliest_occupancy_ts(conn, s.scode)
    if from_ts is None:
        return 0
    from_ts = features.truncate_to_step(from_ts)
    to_ts = now

    raw_occ = occupancy.occupancy_map(conn, s.scode, from_ts, to_ts)
    occ = features.normalize(raw_occ, s.capacity)

    inputs = features.Inputs(
        occupancy=occ,
        mean_7d=features.rolling_mean_7d(occ, from_ts, to_ts),
        holidays=holiday_map,
        weather=weather_map,
    )

    x_rows: list[list[float]] = []
    y_rows: list[float] = []
    to_unix = int(to_ts.timestamp())
    anchor_unix = int(from_ts.timestamp())
    while anchor_unix <= to_unix:
        anchor = datetime.fromtimestamp(anchor_unix, tz=timezone.utc)
        for h in features.TRAINING_HORIZONS_MINUTES:
            target_unix = anchor_unix + h * 60
            if target_unix > to_unix:
                continue  # no label for a horizon that hasn't happened yet
            label = occ.get(target_unix)
            if label is None:
                continue
            target = datetime.fromtimestamp(target_unix, tz=timezone.utc)
            row, ok = features.build(target, anchor, inputs)
            if not ok:
                continue
            x_rows.append(row)
            y_rows.append(label)
        anchor_unix += features.STEP_SECONDS

    if len(x_rows) < min_rows:
        return len(x_rows)

    model = forest.fit(x_rows, y_rows, forest_cfg)
    blob = forest.marshal(model)
    models.save_model(conn, s.scode, blob, datetime.now(timezone.utc), len(x_rows))

    return len(x_rows)


if __name__ == "__main__":
    main()
