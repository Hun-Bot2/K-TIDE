"""LoRA SFT for Qwen2.5-1.5B-Instruct (runs on a Colab T4 or any CUDA GPU).

Precision: FP16 mixed precision on T4 (no BF16 support), BF16 when the GPU supports it.
The base weights are frozen; LoRA adapters are kept in FP32 (peft autocast_adapter_dtype).

Usage:
    python -m ktide.train.sft --qa data_private/train/m1_lecture_only/qa.jsonl --variant translated \
        --condition M1 --out outputs/M1
Outputs (in --out): adapter/, train_config.json, train_log.json
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from ktide.train.data import Collator, build, load_qa

BASE = "Qwen/Qwen2.5-1.5B-Instruct"
TARGETS = {
    "attn": ["q_proj", "k_proj", "v_proj", "o_proj"],
    "all-linear": ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--qa", type=Path, nargs="+", required=True)
    ap.add_argument("--variant", choices=["translated", "preserved"], required=True)
    ap.add_argument("--condition", required=True, help="e.g. M1, M2, M3, M4, ASSIGN")
    ap.add_argument("--out", type=Path, required=True)
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
    args = ap.parse_args(argv)

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
    bf16 = torch.cuda.is_bf16_supported()
    revision = args.revision or HfApi().model_info(args.base).sha

    tok = AutoTokenizer.from_pretrained(args.base, revision=revision)
    system_prompt = load_professor_notebook().system_prompt
    rows = load_qa(args.qa, args.variant)
    train, val = build(tok, system_prompt, rows, args.max_len, args.val_ratio, args.seed)

    model = AutoModelForCausalLM.from_pretrained(
        args.base,
        revision=revision,
        dtype=torch.bfloat16 if bf16 else torch.float16,
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

    args.out.mkdir(parents=True, exist_ok=True)
    targs = TrainingArguments(
        output_dir=str(args.out / "trainer"),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch,
        per_device_eval_batch_size=args.batch,
        gradient_accumulation_steps=args.accum,
        learning_rate=args.lr,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        weight_decay=0.0,
        logging_steps=5,
        eval_strategy="epoch" if val else "no",
        save_strategy="no",
        report_to=[],
        seed=args.seed,
        fp16=not bf16,
        bf16=bf16,
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
    t0 = time.time()
    trainer.train()
    seconds = time.time() - t0

    model.save_pretrained(args.out / "adapter")
    config = {
        "condition": args.condition,
        "base": args.base,
        "revision": revision,
        "variant": args.variant,
        "qa_files": [str(p) for p in args.qa],
        "n_train": len(train),
        "n_val": len(val),
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
        },
        "max_len": args.max_len,
        "seed": args.seed,
        "precision": "bf16" if bf16 else "fp16",
        "gpu": torch.cuda.get_device_name(0),
        "trainable_params": trainable,
        "total_params": total,
        "train_seconds": round(seconds, 1),
        "system_prompt": "professor evaluation prompt (fixed)",
    }
    (args.out / "train_config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (args.out / "train_log.json").write_text(
        json.dumps(trainer.state.log_history, indent=1), encoding="utf-8"
    )
    print(
        json.dumps({k: config[k] for k in ("condition", "n_train", "precision", "train_seconds")})
    )


if __name__ == "__main__":
    main()
