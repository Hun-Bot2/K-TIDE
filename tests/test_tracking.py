import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from ktide.tracking import RETIRED_RUN_IDS, Receipt, collect, retire, sync


def test_duplicate_sync_and_remote_readback(monkeypatch):
    receipt = Receipt(
        ("research",),
        "controlled",
        "example",
        "training",
        "not_applicable",
        "fixture",
        ("sample@v1",),
        (),
        {"loss": 0.25},
    )
    remote = {}

    @contextmanager
    def init(*, entity, project, id, resume, config, settings, job_type, group, tags, **kwargs):
        assert resume == "allow" and project == "K-TIDE"
        assert settings.x_disable_meta and settings.disable_code
        yield remote.setdefault(
            f"{entity}/{project}/{id}",
            SimpleNamespace(
                name=None, config=config, summary={}, tags=tags, group=group, job_type=job_type
            ),
        )

    api = SimpleNamespace(api_key=True, flush=lambda: None, run=remote.__getitem__)
    monkeypatch.setitem(
        sys.modules,
        "wandb",
        SimpleNamespace(
            Api=lambda **kwargs: api, Settings=SimpleNamespace, init=init, teardown=lambda: None
        ),
    )
    sync([receipt], "team")
    sync([receipt], "team")
    assert len(remote) == 1
    stored = next(iter(remote.values()))
    assert stored.name == receipt.display_name
    assert stored.tags == ("research",) and stored.group == "controlled"

    monkeypatch.setattr("ktide.tracking.sleep", lambda _: None)
    results = iter([SimpleNamespace(**{**vars(stored), "summary": {}}), stored])
    api.run = lambda path: next(results)
    sync([receipt], "team")  # eventual consistency: second readback matches

    for change in ({"summary": {"loss": 0.5}}, {"tags": ["course"]}, {"group": "optimization"}):
        api.run = lambda path, change=change: SimpleNamespace(**{**vars(stored), **change})
        with pytest.raises(ValueError, match="readback mismatch"):
            sync([receipt], "team")


def test_optimization_runs_stay_out_of_research():
    def make(tracks, group):
        return Receipt(tracks, group, "X", "training", "not_applicable", "x", (), (), {})

    with pytest.raises(ValueError, match="research"):
        make(("course", "research"), "optimization")
    with pytest.raises(ValueError):
        make(("paper",), "controlled")
    assert make(("course",), "optimization").tags == ["course"]


def test_legacy_receipts_when_local_sources_are_available():
    root = Path(__file__).resolve().parents[1]
    if not (root / "data_private/train/m1_lecture_only/coverage.json").is_file():
        pytest.skip("legacy data is private")
    rows = collect(root)
    assert len({row.run_id for row in rows}) == len(rows)
    assert {row.project for row in rows} == {"K-TIDE"}
    assert {row.evaluation_phase for row in rows if row.stage == "evaluation"} == {"preliminary"}
    by_name = {row.condition: row for row in rows}
    assert by_name["B0"].tags == ["course"]
    assert by_name["M0"].tags == ["course", "research"]
    # the common QA build is recorded once; M1 and M2 are separate dataset versions built from it
    build = by_name["lecture-only"].output_datasets
    assert by_name["M1"].input_datasets == build == by_name["M2"].input_datasets
    assert by_name["M1"].output_datasets != by_name["M2"].output_datasets
    assert by_name["CKU-v3"].input_datasets == by_name["CKU-v2.1"].output_datasets


def test_retire_only_listed_runs_and_only_on_yes(monkeypatch):
    deleted = []
    run = SimpleNamespace(name="old", delete=lambda: deleted.append(True))
    api = SimpleNamespace(run=lambda path: run)
    monkeypatch.setitem(sys.modules, "wandb", SimpleNamespace(Api=lambda **kwargs: api))
    with pytest.raises(ValueError, match="refusing"):
        retire("team", ["not-listed"], confirm=lambda prompt: "yes")
    listed = list(RETIRED_RUN_IDS)
    retire("team", listed, confirm=lambda prompt: "no")
    assert deleted == []
    retire("team", listed, confirm=lambda prompt: "yes")
    assert len(deleted) == len(listed)


def test_retired_run_gets_a_new_id():
    root = Path(__file__).resolve().parents[1]
    if not (root / "data_private/train/m1_lecture_only/coverage.json").is_file():
        pytest.skip("legacy data is private")
    ids = {row.run_id for row in collect(root)}
    assert not ids & set(RETIRED_RUN_IDS)
