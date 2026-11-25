"""SFT dataset construction with assistant-only loss masking.

Each QA becomes one chat: [system = the fixed evaluation system prompt, user = question,
assistant = answer]. The model is trained on the assistant answer tokens and the closing
<|im_end|> token only; system and user tokens are masked with -100.

The system prompt is the same one used at evaluation (fixed by the task, never tuned).

Usage (sanity check of masking on real data):
    uv run python -m ktide.train.data --qa data_private/train/m1_lecture_only/qa.jsonl --variant translated --check
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

ANSWER_FIELDS = {"translated": "answer_translated_ko", "preserved": "answer_preserved_ko"}
IGNORE = -100


def load_qa(paths: list[Path], variant: str) -> list[dict]:
    field = ANSWER_FIELDS[variant]
    rows = []
    for p in paths:
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            answer = r.get(field) or r.get(
                "answer_ko"
            )  # extra files may carry a single answer field
            if r.get("question_ko") and answer:
                rows.append(
                    {
                        "id": r.get("qa_id"),
                        "concept_id": r.get("concept_id"),
                        "question": r["question_ko"].strip(),
                        "answer": answer.strip(),
                    }
                )
    return rows


def encode(tokenizer, system_prompt: str, question: str, answer: str, max_len: int) -> dict:
    prompt_msgs = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question},
    ]
    full_msgs = prompt_msgs + [{"role": "assistant", "content": answer}]
    prompt_ids = tokenizer.apply_chat_template(
        prompt_msgs, tokenize=True, add_generation_prompt=True
    )
    full_ids = tokenizer.apply_chat_template(full_msgs, tokenize=True, add_generation_prompt=False)
    if full_ids[: len(prompt_ids)] != prompt_ids:
        raise ValueError("chat template prefix mismatch: cannot mask the prompt safely")
    im_end = tokenizer.convert_tokens_to_ids("<|im_end|>")
    # keep the answer and its closing <|im_end|>; drop the trailing newline the template adds
    last = max(i for i, t in enumerate(full_ids) if t == im_end)
    full_ids = full_ids[: last + 1]
    labels = [IGNORE] * len(prompt_ids) + full_ids[len(prompt_ids) :]
    if len(full_ids) > max_len:
        raise ValueError(f"example longer than max_len ({len(full_ids)} > {max_len})")
    return {"input_ids": full_ids, "labels": labels, "attention_mask": [1] * len(full_ids)}


def build(
    tokenizer, system_prompt: str, rows: list[dict], max_len: int, val_ratio: float, seed: int
):
    rng = random.Random(seed)
    rows = rows[:]
    rng.shuffle(rows)
    n_val = max(1, int(len(rows) * val_ratio)) if len(rows) > 20 else 0
    enc = [encode(tokenizer, system_prompt, r["question"], r["answer"], max_len) for r in rows]
    return enc[n_val:], enc[:n_val]


class Collator:
    def __init__(self, pad_id: int):
        self.pad_id = pad_id

    def __call__(self, batch):
        import torch

        n = max(len(b["input_ids"]) for b in batch)
        out = {"input_ids": [], "labels": [], "attention_mask": []}
        for b in batch:
            pad = n - len(b["input_ids"])
            out["input_ids"].append(b["input_ids"] + [self.pad_id] * pad)
            out["labels"].append(b["labels"] + [IGNORE] * pad)
            out["attention_mask"].append(b["attention_mask"] + [0] * pad)
        return {k: torch.tensor(v) for k, v in out.items()}


def check(tokenizer, system_prompt: str, rows: list[dict]) -> None:
    """Token-level masking test: only the answer and <|im_end|> are trained."""
    r = rows[0]
    e = encode(tokenizer, system_prompt, r["question"], r["answer"], 4096)
    trained = [t for t, lab in zip(e["input_ids"], e["labels"], strict=True) if lab != IGNORE]
    decoded = tokenizer.decode(trained)
    assert decoded == r["answer"] + "<|im_end|>", f"masking mismatch: {decoded!r}"
    assert system_prompt not in decoded and r["question"] not in decoded
    lengths = [
        len(encode(tokenizer, system_prompt, x["question"], x["answer"], 4096)["input_ids"])
        for x in rows
    ]
    print(
        f"masking OK; {len(rows)} examples; tokens max={max(lengths)} mean={sum(lengths) / len(lengths):.0f}"
    )


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--qa", type=Path, nargs="+", required=True)
    ap.add_argument("--variant", choices=list(ANSWER_FIELDS), required=True)
    ap.add_argument("--model", default="Qwen/Qwen2.5-1.5B-Instruct")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    from transformers import AutoTokenizer

    from ktide.professor import load_professor_notebook

    tok = AutoTokenizer.from_pretrained(args.model)
    rows = load_qa(args.qa, args.variant)
    check(tok, load_professor_notebook().system_prompt, rows)


if __name__ == "__main__":
    main()
