"""Check that training, validation, during-development and held-out test data are separate.

Checks (questions are compared after whitespace/punctuation normalization):
- eval items: unique ids, one split each, no duplicate or near-duplicate questions across splits
- training QA: no duplicate questions inside the file (the train/validation split is drawn from
  it, so a duplicate would leak across train and validation)
- training QA vs eval questions: no exact or near-duplicate questions
- held-out unseen concepts never appear in the training QA

Near-duplicate = character 3-gram Jaccard similarity >= 0.8.

Usage:
    uv run python -m ktide.evalset.split_check --qa data_private/train/m1_lecture_only/qa.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from ktide.evalset.score import load_eval, split_label

NEAR = 0.8


def norm(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text.lower())


def grams(text: str) -> set[str]:
    t = norm(text)
    return {t[i : i + 3] for i in range(max(1, len(t) - 2))}


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def near_pairs(left: list[str], right: list[str], same: bool = False) -> list[tuple]:
    gl, gr = [grams(x) for x in left], [grams(x) for x in right]
    pairs = []
    for i, a in enumerate(gl):
        for j, b in enumerate(gr):
            if same and j <= i:
                continue
            score = jaccard(a, b)
            if score >= NEAR:
                pairs.append((i, j, round(score, 3)))
    return pairs


def check(qa_paths: list[Path], items: dict | None = None) -> dict:
    items = items if items is not None else load_eval()
    eval_rows = list(items.values())
    eval_q = [r["question_ko"] for r in eval_rows]
    splits = [split_label(r.get("split")) for r in eval_rows]
    train = [
        json.loads(line)
        for p in qa_paths
        for line in p.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    train_q = [r["question_ko"] for r in train]

    cross_eval = [
        (i, j, s) for i, j, s in near_pairs(eval_q, eval_q, same=True) if splits[i] != splits[j]
    ]
    exact_train = Counter(norm(q) for q in train_q)
    unseen = {r["concept_id"] for r in eval_rows if r.get("split") == "test_unseen"}
    train_concepts = {r.get("concept_id") for r in train}
    train_vs_eval = near_pairs(train_q, eval_q)
    report = {
        "eval_items": len(eval_rows),
        "eval_split_counts": dict(Counter(splits)),
        "training_qa": len(train),
        "eval_duplicate_ids": len(eval_rows) - len({r["item_id"] for r in eval_rows}),
        "eval_cross_split_near_duplicates": len(cross_eval),
        "training_internal_duplicates": sum(c - 1 for c in exact_train.values() if c > 1),
        "training_vs_eval_near_duplicates": len(train_vs_eval),
        "training_vs_eval_by_split": dict(Counter(splits[j] for _, j, _ in train_vs_eval)),
        "unseen_concepts_in_training": len(unseen & train_concepts),
        "max_training_vs_eval_similarity": max(
            (jaccard(a, b) for a in map(grams, train_q) for b in map(grams, eval_q)), default=0.0
        ),
        "near_duplicate_threshold": NEAR,
    }
    report["max_training_vs_eval_similarity"] = round(report["max_training_vs_eval_similarity"], 3)
    report["passed"] = not any(
        report[k]
        for k in (
            "eval_duplicate_ids",
            "eval_cross_split_near_duplicates",
            "training_internal_duplicates",
            "training_vs_eval_near_duplicates",
            "unseen_concepts_in_training",
        )
    )
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--qa", type=Path, nargs="+", required=True)
    args = ap.parse_args(argv)
    report = check(args.qa)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
