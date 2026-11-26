"""LoRA SFT for Qwen2.5-1.5B-Instruct (runs on a Colab T4 or any CUDA GPU).

Precision: BF16 only on GPUs with native support (compute capability >= 8.0); FP16 otherwise
(T4). `torch.cuda.is_bf16_supported()` also reports emulated BF16 on a T4, so it is not used.
The base weights are frozen; LoRA adapters are kept in FP32 (peft autocast_adapter_dtype).

W&B (opt-in, --report-to wandb): the Trainer's W&B callback logs loss, learning rate, grad norm
and validation loss live; GPU metrics are sampled by the W&B SDK. Model upload, gradient
watching, code saving and console capture are off. If W&B cannot be reached the run falls back
to offline mode and training continues; local outputs are written in every case.

Run ids: a single run passes --run-id (made by the notebook); a sweep agent sets the id itself.
Either way the actual W&B run id names the output folder (<out-root>/<run id>).

Usage:
    python -m ktide.train.sft --qa data_private/train/m1_lecture_only/qa.jsonl --variant translated \
        --condition M1 --out-root outputs --report-to wandb --track research
Outputs (in <out-root>/<run id>/ or --out): adapter/, train_config.json, train_log.json
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from ktide.artifacts import sha256_json
from ktide.train.data import Collator, build, load_qa

BASE = "Qwen/Qwen2.5-1.5B-Instruct"
TARGETS = {
    "attn": ["q_proj", "k_proj", "v_proj", "o_proj"],
    "all-linear": ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
}
# W&B placement (mirrors ktide.tracking): research = controlled 2x2, course = assignment tuning
PLACEMENT = {
    "research": {"group": "controlled", "tags": ["course", "research"], "phase": "controlled"},
    "course": {"group": "optimization", "tags": ["course"], "phase": "optimization"},
    "smoke": {"group": "smoke", "tags": ["smoke"], "phase": "smoke"},
}


def parse(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--qa", type=Path, nargs="+", required=True)
    ap.add_argument("--variant", choices=["translated", "preserved"], required=True)
    ap.add_argument("--condition", required=True, help="e.g. M1, M2, M3, M4, ASSIGN")
    out = ap.add_mutually_exclusive_group(required=True)
    out.add_argument("--out", type=Path, help="fixed output folder")
    out.add_argument("--out-root", type=Path, help="output folder = <out-root>/<run id>")
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--revision", default=None)
    ap.add_argument("--epochs", type=float, default=3)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--r", type=int, default=16)
    ap.add_argument("--alpha", type=int, default=32)
    ap.add_argument("--dropout", type=float, default=0.05)
    ap.add_argument("--targets", choices=list(TARGETS), default="all-linear")
    ap.add_argument("--max-len", type=int, default=256)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--accum", type=int, default=4)
    ap.add_argument("--val-ratio", type=float, default=0.05)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--precision", choices=["auto", "fp16", "bf16"], default="auto")
    ap.add_argument("--max-steps", type=int, default=-1, help="smoke test: stop after N steps")
    ap.add_argument("--report-to", choices=["none", "wandb"], default="none")
    ap.add_argument("--track", choices=list(PLACEMENT), default="research")
    ap.add_argument("--run-id", default=None, help="W&B run id for a single run")
    ap.add_argument("--data-label", default="", help="training data label, e.g. data-v1")
    ap.add_argument("--bundle-manifest", type=Path, default=Path("bundle_manifest.json"))
    args = ap.parse_args(argv)
    if args.track == "research" and os.environ.get("WANDB_SWEEP_ID"):
        ap.error("research (controlled) runs use the fixed recipe; sweeps are for --track course")
    if args.max_steps > 0 and args.track != "smoke":
        ap.error("--max-steps is for smoke tests; use --track smoke")
    return args


class NumericsMonitor:
    """FP16 health: gradient-scale changes (a decrease = an overflow step the scaler skipped) and
    non-finite loss / grad-norm / eval-loss values in the Trainer logs. Observes only."""

    def __new__(cls, trainer):
        from transformers import TrainerCallback

        class _Monitor(TrainerCallback):
            def __init__(self):
                self.trainer = trainer
                self.scale_prev = None
                self.scale_decreases = 0
                self.nonfinite = 0
                self.scale_min = None

            def _scaler(self):
                accelerator = getattr(self.trainer, "accelerator", None)
                return getattr(accelerator, "scaler", None) if accelerator else None

            def on_step_end(self, args, state, control, **kwargs):
                scaler = self._scaler()
                if scaler is None or not scaler.is_enabled():
                    return
                scale = float(scaler.get_scale())
                if self.scale_prev is not None and scale < self.scale_prev:
                    self.scale_decreases += 1
                self.scale_prev = scale
                self.scale_min = scale if self.scale_min is None else min(self.scale_min, scale)

            def on_log(self, args, state, control, logs=None, **kwargs):
                import math

                for key in ("loss", "grad_norm", "eval_loss"):
                    value = (logs or {}).get(key)
                    if isinstance(value, float) and not math.isfinite(value):
                        self.nonfinite += 1

            def report(self) -> dict:
                return {
                    "train/nonfinite_steps": self.nonfinite,
                    "train/grad_scale_final": self.scale_prev,
                    "train/grad_scale_min": self.scale_min,
                    "train/grad_scale_decreases": self.scale_decreases if self.scale_prev else None,
                }

        return _Monitor()


def new_run_id() -> str:
    """8 lowercase letters/digits, the W&B run-id format."""
    import secrets
    import string

    return "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(8))


def pick_precision(torch, requested: str) -> str:
    if requested != "auto":
        return requested
    return "bf16" if torch.cuda.get_device_capability(0) >= (8, 0) else "fp16"


def versions() -> dict:
    import importlib.metadata as md

    out = {}
    for name in (
        "torch",
        "transformers",
        "peft",
        "accelerate",
        "safetensors",
        "huggingface_hub",
        "tokenizers",
        "wandb",
    ):
        try:
            out[name] = md.version(name)
        except md.PackageNotFoundError:
            out[name] = None
    return out


def start_wandb(args, identity: dict, config: dict):
    """Open the run before the Trainer so its callback reuses it. Falls back to offline mode."""
    import wandb

    os.environ.setdefault("WANDB_PROJECT", "K-TIDE")
    os.environ["WANDB_LOG_MODEL"] = "false"  # never upload checkpoints or the model
    os.environ["WANDB_WATCH"] = "false"
    settings = dict(
        console="off",
        disable_code=True,
        disable_git=True,
        x_save_requirements=False,
        x_stats_sampling_interval=5.0,
        x_disable_meta=True,
        init_timeout=90,
    )
    place = PLACEMENT[args.track]
    kwargs = dict(
        project=os.environ["WANDB_PROJECT"],
        entity=os.environ.get("WANDB_ENTITY"),
        name=f"{args.condition} · LoRA training ({args.data_label or 'data'})",
        job_type="training",
        group=place["group"],
        tags=place["tags"],
        config={**identity, **config},
    )
    if not os.environ.get("WANDB_SWEEP_ID"):
        kwargs.update(id=args.run_id or new_run_id(), resume="allow")
    try:
        run = wandb.init(settings=wandb.Settings(mode="online", **settings), **kwargs)
        mode = "online"
    except Exception as error:  # noqa: BLE001 - training must not depend on the network
        print(f"[ktide] W&B online init failed ({type(error).__name__}); logging offline")
        run = wandb.init(settings=wandb.Settings(mode="offline", **settings), **kwargs)
        mode = "offline"
    return run, mode


def main(argv=None):
    args = parse(argv)

    import torch
    from huggingface_hub import HfApi
    from peft import LoraConfig, get_peft_model
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        Trainer,
        TrainingArguments,
        set_seed,
    )

    from ktide.professor import load_professor_notebook

    set_seed(args.seed)
    assert torch.cuda.is_available(), "a CUDA GPU is required"
    precision = pick_precision(torch, args.precision)
    revision = args.revision or HfApi().model_info(args.base).sha

    tok = AutoTokenizer.from_pretrained(args.base, revision=revision)
    system_prompt = load_professor_notebook().system_prompt
    rows = load_qa(args.qa, args.variant)
    # same identifier as the W&B data run for this condition (ktide.tracking)
    dataset_version = f"{args.condition}-train@" + sha256_json(
        [[r["question"], r["answer"]] for r in rows]
    )
    train, val = build(tok, system_prompt, rows, args.max_len, args.val_ratio, args.seed)
    manifest = (
        json.loads(args.bundle_manifest.read_text()) if args.bundle_manifest.is_file() else {}
    )

    recipe = {
        "lora": {
            "r": args.r,
            "alpha": args.alpha,
            "dropout": args.dropout,
            "targets": TARGETS[args.targets],
        },
        "optim": {
            "lr": args.lr,
            "epochs": args.epochs,
            "batch": args.batch,
            "accum": args.accum,
            "effective_batch": args.batch * args.accum,
            "scheduler": "cosine",
            "warmup_ratio": 0.03,
            "max_steps": args.max_steps,
        },
        "max_len": args.max_len,
        "seed": args.seed,
        "precision": precision,
        "variant": args.variant,
        "base_revision": revision,
        "tokenizer_revision": revision,  # tokenizer files come from the same base revision
        "gpu": torch.cuda.get_device_name(0),
        "versions": versions(),
        "bundle": {
            k: manifest.get(k)
            for k in ("tag", "sha256_files", "git_commit", "git_dirty", "created")
        },
        "hf_dataset_revision": os.environ.get("KTIDE_HF_DATASET_REVISION"),
        "data_label": args.data_label,
    }

    run, wandb_mode = None, None
    run_id = args.run_id
    if args.report_to == "wandb":
        identity = {
            "schema_version": 2,
            "condition": args.condition,
            "stage": "training",
            "evaluation_phase": "not_applicable",
            "input_datasets": [dataset_version],
            "output_datasets": [],
        }
        phase = PLACEMENT[args.track]["phase"]
        run, wandb_mode = start_wandb(
            args, identity, {"params": recipe, "track": args.track, "study_phase": phase}
        )
        run_id = run.id
        run.config.update({"experiment_id": f"{args.condition}/{run_id}"})
    out = args.out or args.out_root / (run_id or time.strftime("%Y%m%d-%H%M%S"))
    out.mkdir(parents=True, exist_ok=False)  # never reuse an output folder

    model = AutoModelForCausalLM.from_pretrained(
        args.base,
        revision=revision,
        dtype=torch.bfloat16 if precision == "bf16" else torch.float16,
        attn_implementation="sdpa",
        device_map={"": 0},
    )
    model.config.use_cache = False
    lora = LoraConfig(
        r=args.r,
        lora_alpha=args.alpha,
        lora_dropout=args.dropout,
        target_modules=TARGETS[args.targets],
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora, autocast_adapter_dtype=True)
    trainable, total = model.get_nb_trainable_parameters()

    class DS(torch.utils.data.Dataset):
        def __init__(self, data):
            self.data = data

        def __len__(self):
            return len(self.data)

        def __getitem__(self, i):
            return self.data[i]

    targs = TrainingArguments(
        output_dir=str(out / "trainer"),
        run_name=f"{args.condition} · LoRA training ({args.data_label or 'data'})",
        num_train_epochs=args.epochs,
        max_steps=args.max_steps,
        per_device_train_batch_size=args.batch,
        per_device_eval_batch_size=args.batch,
        gradient_accumulation_steps=args.accum,
        learning_rate=args.lr,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        weight_decay=0.0,
        logging_steps=1,
        eval_strategy="epoch" if val and args.max_steps <= 0 else "no",
        save_strategy="no",
        report_to=["wandb"] if run else [],
        seed=args.seed,
        fp16=precision == "fp16",
        bf16=precision == "bf16",
        optim="adamw_torch",
        dataloader_num_workers=0,
        remove_unused_columns=False,
    )
    trainer = Trainer(
        model=model,
        args=targs,
        train_dataset=DS(train),
        eval_dataset=DS(val) if val else None,
        data_collator=Collator(tok.pad_token_id),
    )
    monitor = NumericsMonitor(trainer)
    trainer.add_callback(monitor)

    config = {
        "condition": args.condition,
        "track": args.track,
        "study_phase": PLACEMENT[args.track]["phase"],
        "base": args.base,
        "revision": revision,
        "variant": args.variant,
        "qa_files": [str(p) for p in args.qa],
        "dataset_version": dataset_version,
        "n_train": len(train),
        "n_val": len(val),
        "lora": recipe["lora"],
        "optim": recipe["optim"],
        "max_len": args.max_len,
        "seed": args.seed,
        "precision": precision,
        "gpu": recipe["gpu"],
        "versions": recipe["versions"],
        "bundle": recipe["bundle"],
        "hf_dataset_revision": recipe["hf_dataset_revision"],
        "tokenizer_revision": revision,
        "data_label": args.data_label,
        "trainable_params": trainable,
        "total_params": total,
        "system_prompt": "professor evaluation prompt (fixed)",
        "wandb_run_id": run.id if run else None,
        "wandb_mode": wandb_mode,
        "status": "running",
    }

    def write(status: str, seconds: float | None) -> None:
        config.update(
            status=status,
            train_seconds=round(seconds, 1) if seconds else None,
            numerics=monitor.report(),
        )
        (out / "train_config.json").write_text(
            json.dumps(config, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        (out / "train_log.json").write_text(
            json.dumps(trainer.state.log_history, indent=1), encoding="utf-8"
        )

    t0 = time.time()
    try:
        trainer.train()
    except BaseException:
        write("failed", time.time() - t0)  # keep what was logged locally
        if run:
            run.summary["status"] = "failed"
            run.finish(exit_code=1)
        raise
    seconds = time.time() - t0
    model.save_pretrained(out / "adapter")
    write("finished", seconds)
    if run:
        numerics = monitor.report()
        run.summary.update(
            {k: v for k, v in numerics.items() if v is not None}
            | {
                "train/train_seconds": round(seconds, 1),
                "train/n_train": len(train),
                "train/n_val": len(val),
                "train/trainable_params": trainable,
            }
        )
        run.finish()
    if config["numerics"]["train/nonfinite_steps"]:
        print(f"[ktide] WARNING non-finite loss/grad values: {config['numerics']}")
    print(
        json.dumps(
            {
                k: config[k]
                for k in (
                    "condition",
                    "n_train",
                    "precision",
                    "train_seconds",
                    "wandb_run_id",
                    "wandb_mode",
                )
            }
        )
    )
    print(f"OUTPUT_DIR={out}")


if __name__ == "__main__":
    main()
