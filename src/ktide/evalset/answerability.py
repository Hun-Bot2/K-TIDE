"""Independent answerability check of evaluation items by a different model family (Codex).

For each item the checker sees the question, the reference answer and key points, and judges:
  - unambiguous: the question has one intended answer
  - reference_correct: the reference answer is academically correct and answers the question
  - issues: short explanation when either is false
The checker never edits items; flagged items go to human review.

Input:  data_private/evalset/reviewed_v1.jsonl (falls back to filtered_v1.jsonl)
Output: data_private/evalset/answerability_v1.jsonl, raw responses in answerability_raw/

Usage:
    uv run python -m ktide.evalset.answerability [--batch 25] [--only-missing]
"""

from __future__ import annotations

import argparse
import json
from collections import Counter

from ktide.judge import call_codex, extract_json_array
from ktide.professor import REPO_ROOT

EVAL = REPO_ROOT / "data_private" / "evalset"
OUT = EVAL / "answerability_v1.jsonl"
RAW = EVAL / "answerability_raw"

PROMPT = """당신은 자연어 처리(NLP)와 기계학습 분야의 시험 문항 검수자입니다.
아래 문항마다 질문, 정답, 핵심 요소가 주어집니다. 문항을 고치지 말고 다음 두 가지만 판정하세요.

1. unambiguous: 질문이 하나의 의도된 답으로 수렴하는가? (여러 해석이 가능하거나 조건이 빠졌으면 false)
2. reference_correct: 정답이 학술적으로 정확하고 질문에 직접 답하는가? 계산 문항은 직접 계산해 확인하세요.
   (사소한 표현 차이는 true. 사실 오류, 계산 오류, 질문과 어긋난 답이면 false)

둘 중 하나라도 false이면 issues에 이유를 한두 문장으로 쓰세요. 둘 다 true이면 issues는 빈 문자열입니다.

출력은 마크다운 없이 순수 JSON 배열만:
[{"item_id": "...", "unambiguous": true, "reference_correct": true, "issues": ""}]

문항:
"""


def load_items():
    path = EVAL / "reviewed_v1.jsonl"
    if not path.exists():
        path = EVAL / "filtered_v1.jsonl"
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    supp = EVAL / "filtered_v1.jsonl"  # supplement items may not be in reviewed_v1 yet
    have = {r["item_id"] for r in rows}
    rows += [
        r
        for r in (json.loads(x) for x in supp.read_text(encoding="utf-8").splitlines() if x.strip())
        if r["item_id"] not in have
    ]
    return [r for r in rows if r.get("status") != "rejected"]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=25)
    ap.add_argument("--model", default="gpt-6.2-sol")
    ap.add_argument("--reasoning", default="medium")
    ap.add_argument("--only-missing", action="store_true")
    args = ap.parse_args(argv)

    items = load_items()
    done = {}
    if OUT.exists():
        for line in OUT.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                done[r["item_id"]] = r
    todo = [i for i in items if not (args.only_missing and i["item_id"] in done)]
    RAW.mkdir(parents=True, exist_ok=True)
    for b in range(0, len(todo), args.batch):
        batch = todo[b : b + args.batch]
        body = "\n\n".join(
            f"[item_id] {i['item_id']}\n[질문] {i['question_ko']}\n[정답] {i['reference_answer_ko']}\n"
            f"[핵심 요소] {' | '.join(i.get('key_points_ko', []))}"
            for i in batch
        )
        raw = call_codex(PROMPT + body, args.model, args.reasoning)
        (RAW / f"batch_{b // args.batch:03d}.json").write_text(
            json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        try:
            results = extract_json_array(raw["text"])
        except (ValueError, json.JSONDecodeError):
            print(f"batch {b // args.batch}: could not parse response")
            continue
        ids = {i["item_id"] for i in batch}
        for r in results:
            if r.get("item_id") in ids:
                r["checker"] = {"tool": "codex", "model": args.model, "reasoning": args.reasoning}
                done[r["item_id"]] = r
        OUT.write_text(
            "".join(json.dumps(v, ensure_ascii=False) + "\n" for v in done.values()),
            encoding="utf-8",
        )
        print(f"batch {b // args.batch + 1}/{-(-len(todo) // args.batch)} done")
    flags = Counter(
        ("ambiguous" if not r.get("unambiguous", True) else "")
        + ("|ref_wrong" if not r.get("reference_correct", True) else "")
        for r in done.values()
    )
    print({"checked": len(done), "of": len(items), "flags": dict(flags)})


if __name__ == "__main__":
    main()
