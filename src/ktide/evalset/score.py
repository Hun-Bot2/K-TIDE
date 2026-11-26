"""Score a run on the evaluation set (docs/research/evaluation_protocol.md).

Three metric families, all written into the run directory:

A. Instructor-rubric judge (no reference): the professor's EVAL_SYSTEM_PROMPT, batched, repeated.
   -> eval_rubric_r{k}.json, aggregated in eval_metrics.json["rubric"]
B. Reference-based judge: the judge sees the reference answer and key points and labels each answer
   correct / partial / incorrect. Accuracy = correct rate; score = correct + 0.5 * partial.
   -> eval_ref_r{k}.json, aggregated in eval_metrics.json["reference"]
C. Rule-based: word/sentence limits, required English terms preserved (TPR), language mix.

Every metric is broken down by split, domain, question_type and term_form.
The judge never sees the model name or training condition.

Usage:
    uv run python -m ktide.evalset.score runs/main/M0/<run_id> [--repeats 3] [--batch 20] [--skip-rubric]
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from statistics import mean, pstdev

from ktide.judge import call_codex, extract_json_array
from ktide.metrics import answer_metrics
from ktide.professor import REPO_ROOT, load_professor_notebook

EVAL = REPO_ROOT / "data_private" / "evalset"
FACETS = ("split", "domain", "question_type", "term_form")
# reporting names for eval splits (item ids keep their original prefixes)
SPLIT_LABELS = {"dev": "during_development"}
SLICE_SPLIT = "during_development"


def split_label(split: str | None) -> str | None:
    return SPLIT_LABELS.get(split, split)


REF_PROMPT = """당신은 자연어 처리(NLP) 및 기계학습 과목의 채점관입니다.
문항마다 [질문], [정답], [핵심 요소], [모델 답변]이 주어집니다. 정답과 핵심 요소를 기준으로 모델 답변을 판정하세요.

- correct: 핵심 요소를 모두(또는 본질적으로) 담고 학술적으로 틀린 내용이 없다. 표현이 달라도 의미가 같으면 correct.
- partial: 핵심 요소 일부만 맞거나, 맞는 내용에 사소한 오류·누락이 있다.
- incorrect: 핵심을 틀리거나, 질문과 다른 답이거나, 사실 오류가 핵심에 있다. 용어를 다른 분야의 뜻으로 해석한 경우도 incorrect.

계산 문항은 최종 값이 맞아야 correct입니다. 길이 제약은 판정에 반영하지 마세요(따로 측정합니다).

출력은 마크다운 없이 순수 JSON 배열만:
[{"item_id": "...", "verdict": "correct", "reason": "한 문장"}]

문항:
"""


def read_jsonl(p: Path) -> list:
    return (
        [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
        if p.exists()
        else []
    )


def load_eval() -> dict:
    items = {r["item_id"]: r for r in read_jsonl(EVAL / "reviewed_v1.jsonl")}
    for h in read_jsonl(EVAL / "human_v1.jsonl"):
        h.setdefault("domain", None)
        h.setdefault("question_type", None)
        h.setdefault("term_form", None)
        items[h["item_id"]] = h
    return items


def batches(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


WORKERS = 1  # set from --workers; concurrent Codex calls per pass


def pmap(fn, chunks):
    """Run one Codex call per chunk, WORKERS at a time; results in chunk order."""
    chunks = list(chunks)
    if WORKERS <= 1:
        return [fn(c) for c in chunks]
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        return list(ex.map(fn, chunks))


def rubric_pass(rows, nb, batch, model, reasoning):
    out = {}
    chunks = list(batches(rows, batch))

    def call(chunk):
        body = "\n\n".join(f"[질문] {r['question']}\n[답변] {r['answer']}" for r in chunk)
        return call_codex(f"{nb.eval_system_prompt.rstrip()}\n\n{body}\n", model, reasoning)

    for chunk, raw in zip(chunks, pmap(call, chunks), strict=True):
        try:
            res = extract_json_array(raw["text"])
        except (ValueError, json.JSONDecodeError):
            continue
        for k, r in enumerate(chunk, 1):
            hit = next((x for x in res if int(x.get("question_number", -1)) == k), None)
            if hit:
                s = hit.get("scores", {})
                vals = [s.get(c) for c in ("accuracy", "relevance", "constraints")]
                if all(isinstance(v, (int, float)) for v in vals):
                    out[r["item_id"]] = {
                        "accuracy": vals[0],
                        "relevance": vals[1],
                        "constraints": vals[2],
                        "total": round(mean(vals), 4),
                    }
    return out


def ref_pass(rows, items, batch, model, reasoning):
    out = {}
    chunks = list(batches(rows, batch))

    def call(chunk):
        body = "\n\n".join(
            f"[item_id] {r['item_id']}\n[질문] {r['question']}\n"
            f"[정답] {items[r['item_id']]['reference_answer_ko']}\n"
            f"[핵심 요소] {' | '.join(items[r['item_id']].get('key_points_ko', []))}\n"
            f"[모델 답변] {r['answer']}"
            for r in chunk
        )
        return call_codex(REF_PROMPT + body, model, reasoning)

    for chunk, raw in zip(chunks, pmap(call, chunks), strict=True):
        try:
            res = extract_json_array(raw["text"])
        except (ValueError, json.JSONDecodeError):
            continue
        ids = {r["item_id"] for r in chunk}
        for x in res:
            if x.get("item_id") in ids and x.get("verdict") in ("correct", "partial", "incorrect"):
                out[x["item_id"]] = {"verdict": x["verdict"], "reason": x.get("reason", "")}
    return out


def term_preserved(answer: str, required: list[str]) -> float | None:
    if not required:
        return None
    hits = sum(bool(re.search(re.escape(t), answer, flags=re.IGNORECASE)) for t in required)
    return hits / len(required)


def breakdown(rows, items, value_fn):
    groups = defaultdict(list)
    for r in rows:
        v = value_fn(r)
        if v is None:
            continue
        groups[("all", "all")].append(v)
        it = items[r["item_id"]]
        for f in FACETS:
            key = split_label(it.get(f)) if f == "split" else it.get(f)
            groups[(f, key)].append(v)
    res = defaultdict(dict)
    for (f, k), vals in groups.items():
        res[f][str(k)] = {"n": len(vals), "mean": round(mean(vals), 4)}
    return dict(res)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--batch", type=int, default=20)
    ap.add_argument("--model", default="gpt-6.2-sol")
    ap.add_argument("--reasoning", default="medium")
    ap.add_argument("--skip-rubric", action="store_true")
    ap.add_argument("--skip-ref", action="store_true")
    ap.add_argument("--workers", type=int, default=4, help="concurrent Codex calls")
    ap.add_argument(
        "--split",
        default=None,
        help="LLM-judge only this split (e.g. during_development); rule metrics cover all items",
    )
    ap.add_argument(
        "--rules-only", action="store_true", help="rule-based metrics only (no LLM judge calls)"
    )
    args = ap.parse_args(argv)
    global WORKERS
    WORKERS = args.workers

    run = args.run_dir
    items = load_eval()
    preds = json.loads((run / "predictions.json").read_text(encoding="utf-8"))
    rows = [
        {"item_id": p["question_id"], "question": p["question"], "answer": p["answer"]}
        for p in preds
        if p["question_id"] in items
    ]
    if args.rules_only:
        args.skip_rubric = args.skip_ref = True
    split = split_label(args.split) if args.split else None
    judge_rows = [
        r for r in rows if split is None or split_label(items[r["item_id"]].get("split")) == split
    ]
    if split and not judge_rows:
        raise SystemExit(f"no items in split {split!r}")
    suffix = f"_{split}" if split else ""
    nb = load_professor_notebook()
    meta = {
        "judge": {"tool": "codex", "model": args.model, "reasoning": args.reasoning},
        "repeats": args.repeats,
        "batch": args.batch,
        "n_items": len(rows),
        "judge_split": split,
        "n_judged": len(judge_rows) if not (args.skip_rubric and args.skip_ref) else 0,
    }

    rubric_runs, ref_runs = [], []
    for k in range(1, args.repeats + 1):
        if not args.skip_rubric:
            path = run / f"eval_rubric{suffix}_r{k}.json"
            if not path.exists():
                path.write_text(
                    json.dumps(
                        rubric_pass(judge_rows, nb, args.batch, args.model, args.reasoning),
                        ensure_ascii=False,
                        indent=1,
                    ),
                    encoding="utf-8",
                )
            rubric_runs.append(json.loads(path.read_text(encoding="utf-8")))
        if not args.skip_ref:
            path = run / f"eval_ref{suffix}_r{k}.json"
            if not path.exists():
                path.write_text(
                    json.dumps(
                        ref_pass(judge_rows, items, args.batch, args.model, args.reasoning),
                        ensure_ascii=False,
                        indent=1,
                    ),
                    encoding="utf-8",
                )
            ref_runs.append(json.loads(path.read_text(encoding="utf-8")))
        print(f"repeat {k}/{args.repeats} done")

    metrics = {"meta": meta}
    value_fns = {}  # (section, key) -> per-item value, reused for the split-restricted slices
    if rubric_runs:

        def rub(r, key):
            vals = [x[r["item_id"]][key] for x in rubric_runs if r["item_id"] in x]
            return mean(vals) if vals else None

        for key in ("total", "accuracy", "relevance", "constraints"):
            value_fns[("rubric", key)] = lambda r, key=key: rub(r, key)
        metrics["rubric"] = {
            key: breakdown(rows, items, value_fns[("rubric", key)])
            for key in ("total", "accuracy", "relevance", "constraints")
        }
        per_rep = [mean(v["total"] for v in x.values()) for x in rubric_runs if x]
        metrics["rubric"]["repeat_means"] = [round(v, 4) for v in per_rep]
        metrics["rubric"]["repeat_sd"] = round(pstdev(per_rep), 4) if len(per_rep) > 1 else None
        metrics["rubric"]["coverage"] = [len(x) for x in rubric_runs]
    if ref_runs:
        score = {"correct": 1.0, "partial": 0.5, "incorrect": 0.0}

        def acc(r):
            v = [
                1.0 if x[r["item_id"]]["verdict"] == "correct" else 0.0
                for x in ref_runs
                if r["item_id"] in x
            ]
            return mean(v) if v else None

        def sc(r):
            v = [score[x[r["item_id"]]["verdict"]] for x in ref_runs if r["item_id"] in x]
            return mean(v) if v else None

        value_fns[("reference", "accuracy")] = acc
        value_fns[("reference", "score")] = sc
        metrics["reference"] = {
            "accuracy": breakdown(rows, items, acc),
            "score": breakdown(rows, items, sc),
        }
        per_rep = [
            mean(1.0 if v["verdict"] == "correct" else 0.0 for v in x.values())
            for x in ref_runs
            if x
        ]
        metrics["reference"]["repeat_accuracy"] = [round(v, 4) for v in per_rep]
        metrics["reference"]["repeat_sd"] = round(pstdev(per_rep), 4) if len(per_rep) > 1 else None
        metrics["reference"]["coverage"] = [len(x) for x in ref_runs]

    rule = {r["item_id"]: answer_metrics(r["answer"], None, 128) for r in rows}
    flag = lambda name: lambda r: float(rule[r["item_id"]][name])  # noqa: E731
    value_fns.update(
        {
            ("rules", "word_limit"): flag("within_word_limit"),
            ("rules", "sentence_limit"): flag("within_sentence_limit"),
            ("rules", "both_limits"): lambda r: float(
                rule[r["item_id"]]["within_word_limit"]
                and rule[r["item_id"]]["within_sentence_limit"]
            ),
            ("rules", "term_preservation"): lambda r: term_preserved(
                r["answer"], items[r["item_id"]].get("required_terms", [])
            ),
            ("rules", "han_rate"): flag("has_han"),
            ("rules", "polite_rate"): flag("is_polite"),
            ("rules", "source_mention_rate"): flag("mentions_source"),
        }
    )
    metrics["rules"] = {
        key: breakdown(rows, items, fn)
        for (section, key), fn in value_fns.items()
        if section == "rules"
    }
    # slices restricted to one split, so runs that answered different item sets stay comparable
    dev_rows = [r for r in rows if split_label(items[r["item_id"]].get("split")) == SLICE_SPLIT]
    metrics["slices"] = {
        "split": SLICE_SPLIT,
        **{
            f"{section}/{key}": {
                facet: values
                for facet, values in breakdown(dev_rows, items, fn).items()
                if facet in ("domain", "question_type", "term_form")
            }
            for (section, key), fn in value_fns.items()
        },
    }
    (run / "eval_metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    summary = {
        "rubric_total": metrics.get("rubric", {}).get("total", {}).get("split"),
        "ref_accuracy": metrics.get("reference", {}).get("accuracy", {}).get("split"),
        "word_limit": metrics["rules"]["word_limit"].get("all"),
        "term_preservation": metrics["rules"]["term_preservation"].get("all"),
        "polite_rate": metrics["rules"]["polite_rate"].get("all"),
        "source_mention_rate": metrics["rules"]["source_mention_rate"].get("all"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    from ktide.tracking import record

    record(
        lambda r: r.stage == "evaluation" and r.source_id == run.resolve().name,
        reason="evaluation",
    )


if __name__ == "__main__":
    main()
