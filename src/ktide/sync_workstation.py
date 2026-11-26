"""Pull training results from the workstation and register the new ones locally.

1. rsync the workstation output folder into data_private/workstation/outputs/ (interactive: ssh asks
   for the password in this terminal)
2. find result zips that were not imported yet (a zip holding train_config.json and run/<dir>/)
3. for each new zip: ktide.import_colab (training run + export checks -> W&B) and rule-based scoring
   (evaluation run -> W&B). LLM-judge scoring stays a separate, explicit step.

Host and folders come from data_private/workstation/config.json (gitignored), e.g.
    {"host": "user@workstation", "remote_dir": "K-TIDE/data_private/workstation/outputs/"}

Usage:
    uv run python -m ktide.sync_workstation              # rsync + import new results
    uv run python -m ktide.sync_workstation --no-rsync   # only import zips already copied
    uv run python -m ktide.sync_workstation --dry-run    # show what would be imported
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

from ktide.professor import REPO_ROOT

FOLDER = REPO_ROOT / "data_private" / "workstation"
CONFIG = FOLDER / "config.json"
LEDGER = FOLDER / "imported.json"


def is_result_zip(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
    except zipfile.BadZipFile:
        return False
    return "train_config.json" in names and any(n.startswith("run/") for n in names)


def pending(outputs: Path, ledger: dict) -> list[Path]:
    found = []
    for path in sorted(outputs.rglob("*.zip")):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest not in ledger and is_result_zip(path):
            found.append(path)
    return found


def rsync(config: dict, outputs: Path) -> None:
    outputs.mkdir(parents=True, exist_ok=True)
    source = f"{config['host']}:{config['remote_dir'].rstrip('/')}/"
    print(f"rsync {source} -> {outputs}/  (enter the workstation password if asked)")
    subprocess.run(["rsync", "-av", "--partial", "-e", "ssh", source, f"{outputs}/"], check=True)


def register(path: Path) -> Path:
    """Import one result zip and compute its rule-based metrics (both record to W&B)."""
    from ktide.import_colab import import_zip
    from ktide.tracking import record

    dest = import_zip(path)
    record(lambda r: r.source_id == dest.name, reason="workstation import")
    subprocess.run(
        [sys.executable, "-m", "ktide.evalset.score", str(dest), "--repeats", "1", "--rules-only"],
        check=True,
    )
    return dest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--no-rsync", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    config = json.loads(CONFIG.read_text()) if CONFIG.is_file() else {}
    outputs = REPO_ROOT / config.get("local_dir", "data_private/workstation/outputs")
    if not args.no_rsync:
        if "host" not in config or "remote_dir" not in config:
            raise SystemExit(f"set host and remote_dir in {CONFIG.relative_to(REPO_ROOT)}")
        rsync(config, outputs)
    ledger = json.loads(LEDGER.read_text()) if LEDGER.is_file() else {}
    new = pending(outputs, ledger)
    print(f"new result zips: {len(new)}")
    for path in new:
        print("  ", path.relative_to(REPO_ROOT))
    if args.dry_run:
        return 0
    for path in new:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        try:
            dest = register(path)
        except FileExistsError as error:  # imported earlier by hand: remember it, do not redo
            print(f"already imported: {error}")
            dest = None
        ledger[digest] = {
            "zip": str(path.relative_to(REPO_ROOT)),
            "run": str(dest.relative_to(REPO_ROOT)) if dest else None,
        }
        LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=1) + "\n")
        if dest:
            print(f"registered {dest.relative_to(REPO_ROOT)}")
            print(
                f"  LLM judge: uv run python -m ktide.evalset.score {dest.relative_to(REPO_ROOT)}"
                " --repeats 1 --split during_development --workers 4"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
