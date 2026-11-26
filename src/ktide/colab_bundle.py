"""Build a ZIP bundle for Colab training/evaluation runs.

The bundle contains the ktide code plus only the data files a run needs, laid out with the same
relative paths so the code works unchanged. It also carries bundle_manifest.json:
tag, creation time, git commit (and whether the tree was dirty), the SHA-256 of every file,
the training dataset versions, and the train/eval separation check (ktide.evalset.split_check).
The notebook refuses a bundle whose ZIP hash or file hashes do not match.

During development the notebook generates answers only for the during_development split
(eval_v1_prefreeze_during_development_questions.json); held-out test questions are for the final
comparison on the frozen eval set.

Usage:
    uv run python -m ktide.colab_bundle --train data_private/train/m1_lecture_only --tag m1_data-v1
Output: data_private/colab/ktide_bundle_<tag>.zip (and its SHA-256 on stdout)
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import zipfile
from pathlib import Path

from ktide.artifacts import git_sha, sha256_json
from ktide.professor import REPO_ROOT

EVAL_QUESTIONS = "data_private/evalset/eval_v1_prefreeze_questions.json"
DEV_QUESTIONS = "data_private/evalset/eval_v1_prefreeze_during_development_questions.json"
ALWAYS = ["pyproject.toml", "README.md", "data_private/professor/TEST_Qwen25_SFT.ipynb"]


def write_dev_questions(root: Path = REPO_ROOT) -> Path:
    from ktide.evalset.score import load_eval, split_label

    items = load_eval()
    questions = json.loads((root / EVAL_QUESTIONS).read_text(encoding="utf-8"))
    dev = [
        q
        for q in questions
        if split_label(items.get(q["question_id"], {}).get("split")) == "during_development"
    ]
    path = root / DEV_QUESTIONS
    path.write_text(json.dumps(dev, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", type=Path, nargs="*", default=[], help="training data folders/files")
    ap.add_argument(
        "--extra", type=Path, nargs="*", default=[], help="other private files to include"
    )
    ap.add_argument("--tag", required=True)
    args = ap.parse_args(argv)

    from ktide.evalset.split_check import check
    from ktide.train.data import load_qa

    out = REPO_ROOT / "data_private" / "colab" / f"ktide_bundle_{args.tag}.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    write_dev_questions()
    files = [REPO_ROOT / p for p in [*ALWAYS, EVAL_QUESTIONS, DEV_QUESTIONS]]
    files += sorted((REPO_ROOT / "src" / "ktide").rglob("*.py"))
    files += sorted((REPO_ROOT / "src" / "ktide").rglob("*.html"))
    files += sorted((REPO_ROOT / "src" / "ktide").rglob("*.json"))
    for p in [*args.train, *args.extra]:
        p = (REPO_ROOT / p) if not p.is_absolute() else p
        files += sorted(x for x in p.rglob("*") if x.is_file()) if p.is_dir() else [p]
    files = [f for f in files if "__pycache__" not in f.parts]
    missing = [str(f) for f in files if not f.exists()]
    if missing:
        raise FileNotFoundError(missing)

    qa_files = [f for f in files if f.name == "qa.jsonl"]
    datasets = {}
    for qa in qa_files:
        for variant in ("translated", "preserved"):
            rows = load_qa([qa], variant)
            key = f"{qa.relative_to(REPO_ROOT)}:{variant}"
            datasets[key] = sha256_json([[r["question"], r["answer"]] for r in rows])
    separation = check(qa_files) if qa_files else None
    if separation and not separation["passed"]:
        raise SystemExit(f"train/eval separation check failed: {json.dumps(separation)}")

    hashes = {str(f.relative_to(REPO_ROOT)): file_sha(f) for f in files}
    git = git_sha()
    manifest = {
        "tag": args.tag,
        "created": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "git_commit": git["commit"],
        "git_dirty": git["dirty"],
        "files": hashes,
        "sha256_files": sha256_json(sorted(hashes.items())),
        "training_dataset_hashes": datasets,
        "split_check": separation,
        "dev_questions": DEV_QUESTIONS,
    }
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, f.relative_to(REPO_ROOT))
        z.writestr("bundle_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
    print(f"{out} ({out.stat().st_size / 1e6:.1f} MB, {len(files)} files)")
    print(f"BUNDLE_SHA256={file_sha(out)}")


if __name__ == "__main__":
    main()
