"""Generate answers with the professor's own ``load_model`` + ``answer_questions``.

Usage:
    uv run python -m ktide.generate --experiment baseline --condition B0 \
        --model Qwen/Qwen2.5-1.5B-Instruct
    uv run python -m ktide.generate --condition A1 --model-dir checkpoints/merged_xxx

Outputs (in runs/<experiment>/<condition>/<run_id>/):
    config.json, questions.json, answers.json, predictions.json, environment.json, judge_input.txt
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from ktide.artifacts import (
    Prediction,
    Question,
    environment_info,
    new_run_dir,
    read_json,
    sha256_json,
    write_json,
)
from ktide.professor import load_professor_notebook

DEFAULT_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"


def resolve_model_dir(model_id: str, revision: str | None) -> tuple[Path, dict]:
    from huggingface_hub import HfApi, snapshot_download

    info = HfApi().model_info(model_id, revision=revision)
    folder = snapshot_download(model_id, revision=info.sha)
    return Path(folder), {"model_id": model_id, "revision": info.sha}


def effective_generation_config(model, tokenizer, max_new_tokens: int) -> dict:
    """Reproduce what ``model.generate`` will actually use for the notebook's GenerationConfig.

    transformers>=4.50 merges model-specific defaults (model.generation_config) into any field the
    caller left at the global default — depending on the model's saved transformers_version.
    """
    from transformers import GenerationConfig

    cfg = GenerationConfig(
        do_sample=False, num_beams=1, max_new_tokens=max_new_tokens, use_cache=True,
        eos_token_id=tokenizer.eos_token_id, pad_token_id=tokenizer.pad_token_id,
    )
    effective, _ = model._prepare_generation_config(cfg)
    keys = ("do_sample", "num_beams", "max_new_tokens", "temperature", "top_p", "top_k",
            "repetition_penalty", "eos_token_id", "pad_token_id", "use_cache")
    return {
        "model_generation_config": model.generation_config.to_diff_dict(),
        "effective": {k: getattr(effective, k, None) for k in keys},
    }


def build_questions(questions: list[str], prefix: str) -> list[Question]:
    return [
        Question(question_id=f"{prefix}{i:03d}", question=q)
        for i, q in enumerate(questions, 1)
    ]


def judge_input_text(preds: list[Prediction]) -> str:
    return "\n\n".join(f"[질문] {p.question}\n[답변] {p.answer}" for p in preds) + "\n"


def main(argv: list[str] | None = None) -> Path:
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiment", default="baseline")
    ap.add_argument("--condition", default="B0")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="HF hub model id")
    ap.add_argument("--revision", default=None, help="HF revision (resolved to a commit sha)")
    ap.add_argument("--model-dir", default=None, help="local model folder (overrides --model)")
    ap.add_argument("--questions-file", default=None,
                    help="JSON array of {question_id, question}; default = professor public set")
    ap.add_argument("--tag", default=None)
    ap.add_argument("--notes", default="")
    args = ap.parse_args(argv)

    nb = load_professor_notebook()
    if args.questions_file:
        questions = [Question(**q) for q in read_json(Path(args.questions_file))]
        dataset = {"name": Path(args.questions_file).stem, "source": "file"}
    else:
        questions = build_questions(nb.questions, prefix="PUB")
        dataset = {"name": "professor_public", "source": "professor_notebook"}
    ids = [q.question_id for q in questions]
    if len(set(ids)) != len(ids):
        raise ValueError("question_id must be unique")
    dataset["n"] = len(questions)
    dataset["sha256"] = sha256_json([q.model_dump() for q in questions])

    if args.model_dir:
        model_dir, model_ref = Path(args.model_dir), {"model_dir": str(args.model_dir)}
    else:
        model_dir, model_ref = resolve_model_dir(args.model, args.revision)

    run_id, out = new_run_dir(args.experiment, args.condition, args.tag)
    print(f"[run] {out}")

    load_model = nb.fn("load_model")
    answer_questions = nb.fn("answer_questions")
    max_new_tokens = nb.constants["MAX_NEW_TOKENS"]

    t0 = time.time()
    model, tokenizer = load_model(model_dir)
    load_s = time.time() - t0
    device = str(model.get_input_embeddings().weight.device)
    dtype = str(model.dtype)

    gen_cfg = effective_generation_config(model, tokenizer, max_new_tokens)
    official = device.startswith("cuda") and dtype == "torch.float16"

    config = {
        "experiment": args.experiment,
        "condition": args.condition,
        "run_id": run_id,
        "official_conditions": official,
        "model": model_ref,
        "dataset": dataset,
        "inference": {
            "code": "professor_notebook.load_model + answer_questions (executed verbatim)",
            "professor_notebook_sha256": nb.sha256,
            "system_prompt": nb.system_prompt,
            "max_new_tokens": max_new_tokens,
            "batch_size": nb.constants["BATCH_SIZE"],
            "device": device,
            "dtype": dtype,
            "attn_implementation": getattr(model.config, "_attn_implementation", None),
            "padding_side": tokenizer.padding_side,
            "generation_config": gen_cfg,
        },
        "seed": None,  # greedy decoding; no sampling seed involved
        "notes": args.notes,
    }
    write_json(out / "config.json", config)
    write_json(out / "questions.json", [q.model_dump() for q in questions])
    write_json(out / "environment.json", environment_info(device) | {"model_load_seconds": load_s})

    status = "success"
    error = None
    t0 = time.time()
    try:
        answers = answer_questions(model, tokenizer, [q.question for q in questions])
    except Exception as exc:  # noqa: BLE001 — record, never hide
        answers, status, error = [""] * len(questions), "error", repr(exc)
    gen_s = time.time() - t0

    if len(answers) != len(questions):
        raise RuntimeError(f"answer count {len(answers)} != question count {len(questions)}")

    from ktide.metrics import answer_metrics

    preds, rule_rows = [], []
    for i, (q, a) in enumerate(zip(questions, answers, strict=True), 1):
        st = status if status == "error" else ("empty" if not a.strip() else "success")
        preds.append(Prediction(question_number=i, question_id=q.question_id, question=q.question,
                                answer=a, word_count=len(a.split()), generation_status=st))
        n_tok = len(tokenizer(a, add_special_tokens=False).input_ids)
        rule_rows.append({"question_number": i, "question_id": q.question_id,
                          **answer_metrics(a, n_tok, max_new_tokens)})

    write_json(out / "answers.json", answers)
    write_json(out / "predictions.json", [p.model_dump() for p in preds])
    (out / "judge_input.txt").write_text(judge_input_text(preds), encoding="utf-8")
    write_json(out / "rule_metrics.json", rule_rows)
    write_json(out / "generation_log.json", {"status": status, "error": error,
                                              "generation_seconds": gen_s})
    print(f"[done] {len(answers)} answers in {gen_s:.1f}s -> {out}")
    return out


if __name__ == "__main__":
    main()
