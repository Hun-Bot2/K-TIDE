"""Register a Colab training result ZIP (from notebooks/colab_train_lora.ipynb) as a local run.

Layout of the ZIP: run/<run dir>/..., adapter/..., train_config.json, train_log.json,
export_report.json. It becomes:
    runs/main/<condition>/<run dir>/            evaluation answers (as generated on Colab)
    runs/main/<condition>/<run dir>/training/   train_config, train_log, export_report (.json)
    checkpoints/<condition>/<run dir>/adapter/  LoRA adapter (private, gitignored)
Existing run directories are never overwritten.

Usage:
    uv run python -m ktide.import_colab --hf results/M1_data-v1_results.zip   # from the HF repo
    uv run python -m ktide.import_colab ~/Downloads/M1_data-v1_results.zip   # a local file
"""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path, PurePosixPath

from ktide.professor import REPO_ROOT

HF_REPO = "HunBot/K-TIDE-Dataset"
TRAINING_FILES = ("train_config.json", "train_log.json", "export_report.json")


def import_zip(archive: Path, root: Path = REPO_ROOT) -> Path:
    with zipfile.ZipFile(archive) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        for n in names:
            parts = PurePosixPath(n).parts
            if n.startswith("/") or ".." in parts:
                raise ValueError(f"unsafe path in archive: {n}")
        run_dirs = {PurePosixPath(n).parts[1] for n in names if n.startswith("run/")}
        if len(run_dirs) != 1:
            raise ValueError(f"expected exactly one run directory, found {sorted(run_dirs)}")
        run_name = run_dirs.pop()
        config = json.loads(zf.read("train_config.json"))
        condition = config["condition"]
        dest = root / "runs" / "main" / condition / run_name
        adapter_dest = root / "checkpoints" / condition / run_name / "adapter"
        if dest.exists() or adapter_dest.exists():
            raise FileExistsError(f"already imported: {dest}")
        for n in names:
            parts = PurePosixPath(n).parts
            if parts[0] == "run":
                target = dest.joinpath(*parts[2:])
            elif parts[0] == "adapter":
                target = adapter_dest.joinpath(*parts[1:])
            elif n in TRAINING_FILES:
                target = dest / "training" / n
            else:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(n))
    return dest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("archive", help="local ZIP path, or a path inside the HF repo with --hf")
    ap.add_argument("--hf", action="store_true", help=f"download the archive from {HF_REPO}")
    args = ap.parse_args(argv)
    if args.hf:
        from huggingface_hub import hf_hub_download

        archive = Path(hf_hub_download(HF_REPO, args.archive, repo_type="dataset"))
    else:
        archive = Path(args.archive)
    dest = import_zip(archive)
    print(f"imported -> {dest.relative_to(REPO_ROOT)}")
    from ktide.tracking import record

    record(lambda r: r.source_id == dest.name, reason="training/export import")
    print(f"next: uv run python -m ktide.evalset.score {dest.relative_to(REPO_ROOT)} --repeats 1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
