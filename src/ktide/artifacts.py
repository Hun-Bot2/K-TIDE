"""Run directories and JSON artifacts. Runs are append-only: an existing run dir is never reused."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from ktide.professor import REPO_ROOT

RUNS_ROOT = REPO_ROOT / "runs"


class Question(BaseModel):
    question_id: str
    question: str


class Prediction(BaseModel):
    question_number: int
    question_id: str
    question: str
    answer: str
    word_count: int
    generation_status: Literal["success", "empty", "error"]


class JudgeScores(BaseModel):
    accuracy: int | None = Field(default=None, ge=1, le=5)
    relevance: int | None = Field(default=None, ge=1, le=5)
    constraints: int | None = Field(default=None, ge=1, le=5)


class JudgeResult(BaseModel):
    question_number: int
    question_id: str
    scores: JudgeScores
    total_average: float | None  # recomputed by us from the three scores
    judge_reported_average: float | None = None  # as returned by the judge, kept for audit
    feedback: str | None


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_json(obj: Any) -> str:
    blob = json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def git_sha() -> dict:
    def run(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
        ).stdout.strip()

    return {"commit": run("rev-parse", "HEAD") or None, "dirty": bool(run("status", "--porcelain"))}


def new_run_dir(experiment: str, condition: str, tag: str | None = None) -> tuple[str, Path]:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    sha = (git_sha()["commit"] or "nogit")[:7]
    run_id = f"{stamp}_{sha}" + (f"_{tag}" if tag else "")
    path = RUNS_ROOT / experiment / condition / run_id
    path.mkdir(parents=True, exist_ok=False)  # never overwrite
    return run_id, path


def environment_info(device: str | None = None) -> dict:
    import torch
    import transformers

    info: dict[str, Any] = {
        "execution_date": dt.datetime.now().astimezone().isoformat(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "torch": torch.__version__,
        "transformers": transformers.__version__,
        "cuda_available": torch.cuda.is_available(),
        "mps_available": torch.backends.mps.is_available(),
        "device": device,
        "git": git_sha(),
    }
    for pkg in ("accelerate", "safetensors", "huggingface_hub", "tokenizers"):
        try:
            info[pkg] = __import__(pkg).__version__
        except Exception:  # noqa: BLE001
            info[pkg] = None
    if torch.cuda.is_available():
        info["gpu"] = torch.cuda.get_device_name(0)
        info["cuda"] = torch.version.cuda
    return info
