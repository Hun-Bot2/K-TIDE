"""Merge a LoRA adapter into the base model and package it for the evaluation notebook.

Steps:
  1. Load the base in FP32, merge the adapter, cast to FP16, save safetensors.
  2. Copy the base model's tokenizer files and generation_config.json byte-for-byte (ADR-0001:
     save_pretrained would re-stamp generation_config.json and turn greedy decoding into sampling).
  3. ZIP as a single folder; verify with the professor's own unpack_model, check that the effective
     decoding is greedy, and that the package is under the size limit.

Usage:
    python -m ktide.train.export --adapter outputs/M1/adapter --out outputs/M1/package [--name qwen25_sft_model]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

COPY_FROM_BASE = (
    "generation_config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
    "merges.txt",
)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 24), b""):
            h.update(b)
    return h.hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--name", default="qwen25_sft_model")
    args = ap.parse_args(argv)

    import torch
    from huggingface_hub import snapshot_download
    from peft import PeftModel
    from transformers import AutoModelForCausalLM

    from ktide.check_generation_config import effective
    from ktide.professor import load_professor_notebook

    cfg = json.loads((args.adapter.parent / "train_config.json").read_text(encoding="utf-8"))
    base_dir = Path(snapshot_download(cfg["base"], revision=cfg["revision"]))
    folder = args.out / args.name
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)

    model = AutoModelForCausalLM.from_pretrained(base_dir, dtype=torch.float32)
    model = PeftModel.from_pretrained(model, args.adapter).merge_and_unload()
    model = model.to(torch.float16)
    model.save_pretrained(folder, safe_serialization=True)
    for name in COPY_FROM_BASE:
        shutil.copy2(base_dir / name, folder / name)
    for f in folder.iterdir():  # keep only files the evaluation notebook accepts
        if f.name not in {
            "config.json",
            "model.safetensors",
            "model.safetensors.index.json",
            *COPY_FROM_BASE,
        } and not f.name.startswith("model-"):
            f.unlink()

    zpath = args.out / f"{args.name}.zip"
    with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_STORED) as z:
        for f in sorted(folder.iterdir()):
            z.write(f, f"{args.name}/{f.name}")

    nb = load_professor_notebook()
    with tempfile.TemporaryDirectory() as tmp:
        nb.fn("unpack_model")(zpath, Path(tmp) / "m")  # raises if the package is invalid
        from transformers import AutoTokenizer, GenerationConfig, Qwen2Config, Qwen2ForCausalLM

        conf = Qwen2Config.from_pretrained(Path(tmp) / "m")
        with torch.device("meta"):
            meta = Qwen2ForCausalLM(conf)
        meta.generation_config = GenerationConfig.from_pretrained(Path(tmp) / "m")
        eff = effective(meta, AutoTokenizer.from_pretrained(Path(tmp) / "m"))
    assert eff["do_sample"] is False and eff["repetition_penalty"] == 1.0, f"not greedy: {eff}"
    size = zpath.stat().st_size
    assert size <= nb.constants["MAX_PACKAGE_BYTES"], "package exceeds the size limit"
    for name in COPY_FROM_BASE:
        assert sha256(folder / name) == sha256(base_dir / name), f"{name} differs from the base"
    report = {
        "zip": str(zpath),
        "bytes": size,
        "sha256": sha256(zpath),
        "effective_generation": eff,
        "files": sorted(f.name for f in folder.iterdir()),
        "professor_unpack_model": "ok",
        "base_files_identical": list(COPY_FROM_BASE),
    }
    (args.out / "export_report.json").write_text(
        json.dumps(report, indent=1, default=str), encoding="utf-8"
    )
    print(json.dumps({k: report[k] for k in ("zip", "bytes", "professor_unpack_model")}))


if __name__ == "__main__":
    main()
