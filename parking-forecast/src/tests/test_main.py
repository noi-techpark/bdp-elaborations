# SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import pytest

import main as main_module


@pytest.fixture
def stub_jobs(monkeypatch):
    calls = []
    for job in main_module.JOBS:
        monkeypatch.setitem(main_module.JOBS, job, lambda job=job: calls.append(job))
    return calls


def test_dispatches_to_the_named_job(stub_jobs):
    main_module.main(["train"])
    assert stub_jobs == ["train"]


def test_pipeline_runs_ingest_then_train_then_predict(stub_jobs):
    main_module.main(["pipeline"])
    assert stub_jobs == ["ingest", "train", "predict"]


def test_rejects_an_unknown_job(stub_jobs):
    with pytest.raises(SystemExit):
        main_module.main(["nonexistent"])
    assert stub_jobs == []
