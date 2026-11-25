"""Build a private ZIP bundle for Colab training/evaluation runs.

The bundle contains the ktide code plus only the private files a run needs, laid out with the same
relative paths so the code works unchanged. Upload it to your Google Drive (private), never to a
public place.

Usage:
    uv run python -m ktide.colab_bundle --train data_private/train/m1_lecture_only --tag m1
Output: data_private/colab/ktide_bundle_<tag>.zip
"""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

from ktide.professor import REPO_ROOT

ALWAYS = [
    "pyproject.toml",
    "data_private/professor/TEST_Qwen25_SFT.ipynb",
    "data_private/evalset/eval_v1_prefreeze_questions.json",
]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", type=Path, nargs="*", default=[], help="training data folders/files")
    ap.add_argument(
        "--extra", type=Path, nargs="*", default=[], help="other private files to include"
    )
    ap.add_argument("--tag", required=True)
    args = ap.parse_args(argv)

    out = REPO_ROOT / "data_private" / "colab" / f"ktide_bundle_{args.tag}.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    files = [REPO_ROOT / p for p in ALWAYS]
    files += sorted((REPO_ROOT / "src" / "ktide").rglob("*.py"))
    files += sorted((REPO_ROOT / "src" / "ktide").rglob("*.html"))
    for p in [*args.train, *args.extra]:
        p = (REPO_ROOT / p) if not p.is_absolute() else p
        files += sorted(x for x in p.rglob("*") if x.is_file()) if p.is_dir() else [p]
    missing = [str(f) for f in files if not f.exists()]
    if missing:
        raise FileNotFoundError(missing)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for f in files:
            if "__pycache__" not in f.parts:
                z.write(f, f.relative_to(REPO_ROOT))
    print(f"{out} ({out.stat().st_size / 1e6:.1f} MB, {len(files)} files)")


if __name__ == "__main__":
    main()
