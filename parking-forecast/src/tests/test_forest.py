# SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import random

from forecasting import forest


def test_fit_recovers_signal():
    """Checks the forest learns a simple non-linear, interaction-bearing
    function (the kind of hour-x-weather interaction we rely on it to pick
    up automatically) substantially better than predicting the mean.
    """
    rng = random.Random(42)

    n = 4000
    x = []
    y = []
    for _ in range(n):
        hour = rng.random() * 24
        weather = round(rng.random() * 3)  # 0..3
        peak = 1.0 if 7 < hour < 10 else 0.0
        noise = rng.gauss(0, 0.05)
        x.append([hour, weather])
        y.append(0.3 + 0.5 * peak - 0.2 * peak * weather + noise)

    cfg = forest.Config(num_trees=30)
    model = forest.fit(x, y, cfg)

    mean_y = sum(y) / n

    sse, sse_baseline = 0.0, 0.0
    test_n = 500
    for _ in range(test_n):
        hour = rng.random() * 24
        weather = round(rng.random() * 3)
        peak = 1.0 if 7 < hour < 10 else 0.0
        want = 0.3 + 0.5 * peak - 0.2 * peak * weather

        mean, lo, hi = forest.predict_stats(model, [hour, weather], 0.1, 0.9)
        assert lo <= hi
        assert lo <= mean <= hi

        sse += (mean - want) ** 2
        sse_baseline += (mean_y - want) ** 2

    assert sse < sse_baseline * 0.3


def test_marshal_round_trip():
    rng = random.Random(1)
    n = 200
    x = [[rng.random(), rng.random()] for _ in range(n)]
    y = [row[0] + 2 * row[1] for row in x]

    cfg = forest.Config(num_trees=5)
    model = forest.fit(x, y, cfg)

    blob = forest.marshal(model)
    model2 = forest.unmarshal(blob)

    point = [0.4, 0.6]
    m1, _, _ = forest.predict_stats(model, point, 0.1, 0.9)
    m2, _, _ = forest.predict_stats(model2, point, 0.1, 0.9)
    assert m1 == m2
