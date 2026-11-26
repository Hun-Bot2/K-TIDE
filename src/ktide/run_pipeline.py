"""Run one training condition end to end from a terminal (lab server, RunPod, any CUDA machine).

Same steps and modules as notebooks/colab_train_lora.ipynb, run inside an extracted bundle:
  1. bundle check (manifest file hashes, train/eval separation check)
  2. token-level loss-masking check
  3. LoRA SFT (live W&B run; output folder named by the W&B run id)
  4. merge + package + verify (professor unpack_model, greedy decoding, size limit)   [full]
  5. answers for the during_development split (professor load_model + answer_questions) [full]
  6. pack results and upload them to the Hugging Face dataset repo                   [full]

Secrets come from the environment: WANDB_API_KEY (W&B), HF_TOKEN (upload). Every step's output is
written locally first; a failed upload leaves the results zip on disk.

Usage (inside the extracted bundle folder):
    PYTHONPATH=src python -m ktide.run_pipeline --mode smoke
    PYTHONPATH=src python -m ktide.run_pipeline --mode full
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import secrets
import shutil
import string
import subprocess
import sys
from pathlib import Path


def run(work: Path, *args: str) -> list[str]:
    """`python -m <module> ...` in the bundle folder, streaming output; returns the lines."""
    env = {**os.environ, "PYTHONPATH": str(work / "src")}
    proc = subprocess.Popen(
        [sys.executable, "-u", "-m", *args],
        cwd=work,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    lines = []
    for line in proc.stdout:
        print(line, end="", flush=True)
        lines.append(line)
    if proc.wait() != 0:
        raise SystemExit(f"{args[0]} failed (exit {proc.returncode}); see the output above")
    return lines


def check_bundle(work: Path, qa: list[str]) -> dict:
    manifest = json.loads((work / "bundle_manifest.json").read_text())
    bad = [
        p
        for p, h in manifest["files"].items()
        if hashlib.sha256((work / p).read_bytes()).hexdigest() != h
    ]
    if bad:
        raise SystemExit(f"files differ from the bundle manifest: {bad[:5]}")
    if manifest["split_check"] is not None and not manifest["split_check"]["passed"]:
        raise SystemExit("train/eval separation check failed in this bundle")
    missing = [f for f in qa if f not in manifest["files"]]
    if missing:
        raise SystemExit(f"training files not in the bundle: {missing}")
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--mode", choices=["smoke", "full"], required=True)
    ap.add_argument("--condition", default="M1")
    ap.add_argument("--variant", default="translated", choices=["translated", "preserved"])
    ap.add_argument("--qa", nargs="+", default=["data_private/train/m1_lecture_only/qa.jsonl"])
    ap.add_argument("--data-label", default="data-v1")
    ap.add_argument("--track", default="research", choices=["research", "course"])
    ap.add_argument("--epochs", default="3")
    ap.add_argument("--lr", default="1e-4")
    ap.add_argument("--r", default="16")
    ap.add_argument("--alpha", default="32")
    ap.add_argument("--targets", default="all-linear")
    ap.add_argument("--precision", default="fp16", help="fixed for every research run")
    ap.add_argument("--smoke-steps", default="8")
    ap.add_argument("--out-root", type=Path, default=Path("../outputs"))
    ap.add_argument("--hf-repo", default="HunBot/K-TIDE-Dataset")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--upload-model-zip", action="store_true", help="final assignment model only")
    args = ap.parse_args(argv)

    work = Path.cwd().resolve()
    os.environ.setdefault("WANDB_PROJECT", "K-TIDE")
    os.environ.setdefault("WANDB_ENTITY", "hun-bot")
    os.environ.update(
        {
            "WANDB_LOG_MODEL": "false",
            "WANDB_WATCH": "false",
            "WANDB_DISABLE_CODE": "true",
            "TOKENIZERS_PARALLELISM": "false",
            "HF_HUB_DISABLE_PROGRESS_BARS": "1",
        }
    )
    for key in ("WANDB_API_KEY", "HF_TOKEN"):
        print(f"{key}: {'set' if os.environ.get(key) else 'NOT SET'}")

    import torch

    if not torch.cuda.is_available():
        raise SystemExit("no CUDA GPU visible (check CUDA_VISIBLE_DEVICES / nvidia-smi)")
    manifest = check_bundle(work, args.qa)
    print(
        "python",
        sys.version.split()[0],
        "| torch",
        torch.__version__,
        "|",
        torch.cuda.get_device_name(0),
        "| bundle",
        manifest["tag"],
        (manifest["git_commit"] or "")[:7],
        "dirty" if manifest["git_dirty"] else "",
    )

    run(work, "ktide.train.data", "--qa", *args.qa, "--variant", args.variant, "--check")

    smoke = args.mode == "smoke"
    run_id = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(8))
    out_root = (work / args.out_root).resolve()
    sft = [
        "ktide.train.sft",
        "--qa",
        *args.qa,
        "--variant",
        args.variant,
        "--condition",
        args.condition,
        "--out-root",
        str(out_root),
        "--run-id",
        run_id,
        "--report-to",
        "wandb",
        "--track",
        "smoke" if smoke else args.track,
        "--data-label",
        args.data_label,
        "--bundle-manifest",
        str(work / "bundle_manifest.json"),
        "--epochs",
        args.epochs,
        "--lr",
        args.lr,
        "--r",
        args.r,
        "--alpha",
        args.alpha,
        "--targets",
        args.targets,
        "--precision",
        args.precision,
    ]
    if smoke:
        sft += ["--max-steps", args.smoke_steps]
    lines = run(work, *sft)
    out = Path([x for x in lines if x.startswith("OUTPUT_DIR=")][-1].split("=", 1)[1].strip())
    print(
        f"W&B run: https://wandb.ai/{os.environ['WANDB_ENTITY']}/{os.environ['WANDB_PROJECT']}"
        f"/runs/{run_id} | output: {out}"
    )
    if smoke:
        numerics = json.loads((out / "train_config.json").read_text()).get("numerics")
        print("smoke test done. FP16 checks:", numerics)
        return 0

    run(
        work, "ktide.train.export", "--adapter", str(out / "adapter"), "--out", str(out / "package")
    )
    run(
        work,
        "ktide.generate",
        "--experiment",
        "main",
        "--condition",
        args.condition,
        "--model-dir",
        str(out / "package" / "qwen25_sft_model"),
        "--questions-file",
        manifest["dev_questions"],
        "--tag",
        f"gpu-{args.data_label}-{run_id}",
        "--notes",
        f"{args.condition} LoRA, variant={args.variant}, {args.data_label}, wandb={run_id}",
    )

    run_dir = Path(glob.glob(str(work / "runs/main" / args.condition / f"*{run_id}*"))[-1])
    res = out_root.parent / "results" / run_id
    shutil.rmtree(res, ignore_errors=True)
    shutil.copytree(run_dir, res / "run" / run_dir.name)
    shutil.copytree(out / "adapter", res / "adapter")
    for name in ("train_config.json", "train_log.json"):
        shutil.copy(out / name, res)
    shutil.copy(out / "package" / "export_report.json", res)
    archive = Path(shutil.make_archive(str(res), "zip", res))
    target = f"results/{args.condition}/{args.data_label}/{run_id}.zip"
    print("results zip:", archive, archive.stat().st_size // 1024, "KB")
    if args.no_upload:
        print("upload skipped; copy the zip to the local machine and run ktide.import_colab")
        return 0
    try:
        from huggingface_hub import HfApi

        api = HfApi()
        api.upload_file(
            path_or_fileobj=str(archive),
            path_in_repo=target,
            repo_id=args.hf_repo,
            repo_type="dataset",
            commit_message=f"{args.condition} {args.data_label} {run_id}",
        )
        if args.upload_model_zip:
            api.upload_file(
                path_or_fileobj=str(out / "package" / "qwen25_sft_model.zip"),
                path_in_repo=f"models/{args.condition}/{args.data_label}/{run_id}.zip",
                repo_id=args.hf_repo,
                repo_type="dataset",
            )
        print("uploaded:", target)
        print("local: uv run python -m ktide.import_colab --hf", target)
    except Exception as error:  # noqa: BLE001 - the zip stays on disk
        print("upload failed (results kept at", archive, "):", type(error).__name__, error)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
