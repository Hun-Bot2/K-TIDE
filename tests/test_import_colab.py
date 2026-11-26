import json
import zipfile

import pytest

from ktide.import_colab import import_zip
from ktide.tracking import collect_runs


def make_zip(path, run_name="20260101-000000_abc_colab-t4-data-v1"):
    config = {
        "condition": "M1",
        "variant": "translated",
        "dataset_version": "M1-train@x",
        "n_train": 10,
        "n_val": 1,
        "train_seconds": 5.0,
        "trainable_params": 100,
        "lora": {"r": 16},
        "optim": {"lr": 1e-4},
        "max_len": 256,
        "seed": 42,
        "precision": "fp16",
        "gpu": "T4",
        "revision": "rev",
    }
    log = [
        {"step": 5, "loss": 2.0, "learning_rate": 1e-4, "epoch": 1.0},
        {"step": 5, "eval_loss": 1.8, "epoch": 1.0},
        {"step": 10, "loss": 1.5, "learning_rate": 5e-5, "epoch": 2.0},
    ]
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(f"run/{run_name}/predictions.json", "[]")
        zf.writestr(f"run/{run_name}/questions.json", "[]")
        zf.writestr("adapter/adapter_config.json", "{}")
        zf.writestr("train_config.json", json.dumps(config))
        zf.writestr("train_log.json", json.dumps(log))
        zf.writestr("export_report.json", "{}")
    return run_name


def test_import_and_training_receipt(tmp_path):
    archive = tmp_path / "r.zip"
    run_name = make_zip(archive)
    dest = import_zip(archive, root=tmp_path)
    assert dest == tmp_path / "runs/main/M1" / run_name
    assert (dest / "training/train_config.json").is_file()
    assert (tmp_path / "checkpoints/M1" / run_name / "adapter/adapter_config.json").is_file()
    with pytest.raises(FileExistsError):
        import_zip(archive, root=tmp_path)

    (rec,) = [r for r in collect_training_only(tmp_path)]
    assert rec.stage == "training" and rec.group == "controlled"
    assert rec.input_datasets == ("M1-train@x",)
    assert rec.metrics["train/final_loss"] == 1.5 and rec.metrics["train/final_eval_loss"] == 1.8
    assert [h["train/global_step"] for h in rec.history] == [5, 5, 10]
    assert rec.history[1] == {"train/global_step": 5, "eval/loss": 1.8, "train/epoch": 1.0}
    assert rec.experiment_id == f"M1/{run_name}"
    assert rec.display_name == "M1 · LoRA training (data-v1)"
    assert rec.config["params"]["variant"] == "translated"


def collect_training_only(root):
    return [r for r in collect_runs(root) if r.stage == "training"]


def test_unsafe_archive_rejected(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("run/x/../../evil.json", "{}")
        zf.writestr("train_config.json", "{}")
    with pytest.raises(ValueError, match="unsafe"):
        import_zip(archive, root=tmp_path)
