import json
import sys
from types import SimpleNamespace

import pytest

from ktide.evalset.score import split_label
from ktide.evalset.split_check import check
from ktide.tracking import collect_runs, placement, record
from ktide.train import sft
from ktide.wandb_workspace import plan


def test_split_label_renames_dev_only():
    assert split_label("dev") == "during_development"
    assert split_label("test_seen") == "test_seen"


def test_sft_guards(monkeypatch):
    base = ["--qa", "x.jsonl", "--variant", "translated", "--condition", "M1", "--out-root", "o"]
    monkeypatch.setenv("WANDB_SWEEP_ID", "abc")
    with pytest.raises(SystemExit):
        sft.parse(base + ["--track", "research"])
    assert sft.parse(base + ["--track", "course"]).track == "course"
    monkeypatch.delenv("WANDB_SWEEP_ID")
    with pytest.raises(SystemExit):
        sft.parse(base + ["--max-steps", "8"])
    assert sft.parse(base + ["--max-steps", "8", "--track", "smoke"]).max_steps == 8


def test_precision_uses_native_bf16_only():
    def torch_with(capability):
        return SimpleNamespace(cuda=SimpleNamespace(get_device_capability=lambda i: capability))

    assert sft.pick_precision(torch_with((7, 5)), "auto") == "fp16"  # T4
    assert sft.pick_precision(torch_with((8, 0)), "auto") == "bf16"
    assert sft.pick_precision(torch_with((7, 5)), "bf16") == "bf16"


def test_wandb_falls_back_to_offline(monkeypatch):
    calls = []

    def init(settings, **kwargs):
        calls.append(settings.mode)
        if settings.mode == "online":
            raise ConnectionError("no network")
        return SimpleNamespace(id=kwargs["id"])

    fake = SimpleNamespace(
        init=init,
        Settings=lambda **kw: SimpleNamespace(**kw),
    )
    monkeypatch.setitem(sys.modules, "wandb", fake)
    monkeypatch.delenv("WANDB_SWEEP_ID", raising=False)
    args = SimpleNamespace(track="research", run_id="rid", condition="M1", data_label="data-v1")
    run, mode = sft.start_wandb(args, {"stage": "training"}, {})
    assert (run.id, mode, calls) == ("rid", "offline", ["online", "offline"])
    import os

    assert os.environ["WANDB_LOG_MODEL"] == "false" and os.environ["WANDB_WATCH"] == "false"


def test_record_never_raises(monkeypatch):
    assert record() is False  # KTIDE_WANDB=0 in tests
    monkeypatch.setenv("KTIDE_WANDB", "1")
    monkeypatch.setattr(
        "ktide.tracking.collect", lambda root: (_ for _ in ()).throw(OSError("offline"))
    )
    assert record(reason="test") is False


def test_placement_and_smoke_runs_skipped(tmp_path):
    assert placement({"track": "course"}) == (("course",), "optimization")
    assert placement({}) == (("course", "research"), "controlled")
    run = tmp_path / "runs/main/M1/r1/training"
    run.mkdir(parents=True)
    (run / "train_config.json").write_text(json.dumps({"track": "smoke", "condition": "M1"}))
    (run / "train_log.json").write_text("[]")
    assert collect_runs(tmp_path) == []


def test_split_check_detects_leaks(tmp_path):
    items = {
        "dev-1": {
            "item_id": "dev-1",
            "split": "dev",
            "question_ko": "Tokenizer의 역할은?",
            "concept_id": "c1",
        },
        "test_unseen-1": {
            "item_id": "test_unseen-1",
            "split": "test_unseen",
            "question_ko": "BLEU는 무엇을 측정하는가?",
            "concept_id": "c9",
        },
    }
    qa = tmp_path / "qa.jsonl"
    rows = [
        {"question_ko": "Tokenizer의 역할은?", "concept_id": "c1"},
        {"question_ko": "ROUGE란 무엇인가?", "concept_id": "c9"},
    ]
    qa.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows))
    report = check([qa], items)
    assert report["training_vs_eval_near_duplicates"] == 1
    assert report["unseen_concepts_in_training"] == 1
    assert not report["passed"]


def test_workspace_plan_is_well_formed():
    sections = plan()
    names = [name for name, _ in sections]
    assert len(names) == len(set(names)) and all(panels for _, panels in sections)
    keys = [k for _, ps in sections for p in ps if p["kind"] == "bar" for k in p["metrics"]]
    assert all("/dev/" not in k for k in keys)


def test_numerics_monitor_counts_overflow_and_nonfinite():
    scales = iter([65536.0, 65536.0, 32768.0, 32768.0])

    class Scaler:
        def is_enabled(self):
            return True

        def get_scale(self):
            return next(scales)

    trainer = SimpleNamespace(accelerator=SimpleNamespace(scaler=Scaler()))
    monitor = sft.NumericsMonitor(trainer)
    for _ in range(4):
        monitor.on_step_end(None, None, None)
    monitor.on_log(None, None, None, logs={"loss": float("nan"), "grad_norm": 1.0})
    monitor.on_log(None, None, None, logs={"eval_loss": float("inf")})
    report = monitor.report()
    assert report["train/grad_scale_decreases"] == 1
    assert report["train/grad_scale_final"] == 32768.0
    assert report["train/nonfinite_steps"] == 2


def test_numerics_monitor_without_scaler():
    monitor = sft.NumericsMonitor(SimpleNamespace(accelerator=SimpleNamespace(scaler=None)))
    monitor.on_step_end(None, None, None)
    assert monitor.report()["train/grad_scale_final"] is None


def test_run_pipeline_bundle_check(tmp_path):
    import hashlib

    from ktide.run_pipeline import check_bundle

    qa = tmp_path / "data_private/train/x/qa.jsonl"
    qa.parent.mkdir(parents=True)
    qa.write_text("{}\n")
    files = {"data_private/train/x/qa.jsonl": hashlib.sha256(qa.read_bytes()).hexdigest()}
    manifest = {"files": files, "split_check": {"passed": True}, "tag": "t"}
    (tmp_path / "bundle_manifest.json").write_text(json.dumps(manifest))
    assert check_bundle(tmp_path, ["data_private/train/x/qa.jsonl"])["tag"] == "t"
    with pytest.raises(SystemExit, match="not in the bundle"):
        check_bundle(tmp_path, ["other.jsonl"])
    qa.write_text("changed\n")
    with pytest.raises(SystemExit, match="differ"):
        check_bundle(tmp_path, ["data_private/train/x/qa.jsonl"])
