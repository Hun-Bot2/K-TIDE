"""Schema checks and automatic filters for evaluation items (docs/research/evaluation_protocol.md).

Input: data_private/evalset/draft/*.jsonl (one item per line, written by the item writers).
Output: data_private/evalset/filtered_v1.jsonl with per-item `auto_checks` and `status`
        (`auto_ok` or `needs_review`), plus a summary printed to stdout.

Nothing is deleted: failing items are kept and flagged so a human can decide.

Usage:
    uv run python -m ktide.evalset.filters
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from ktide.metrics import sentence_count, word_count
from ktide.professor import REPO_ROOT

EVAL = REPO_ROOT / "data_private" / "evalset"
REQUIRED = (
    "item_id",
    "slot_id",
    "split",
    "concept_id",
    "domain",
    "question_type",
    "term_form",
    "variant_group",
    "question_ko",
    "reference_answer_ko",
    "key_points_ko",
    "required_terms",
    "lecture_sources",
    "writer",
)
HANGUL = re.compile(r"[가-힣]")
LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z0-9\-]*")
DUP_THRESHOLD = 0.6
LEAK_THRESHOLD = 0.5


def ngrams(text: str, n: int = 3) -> set[str]:
    t = re.sub(r"\s+", "", text)
    return {t[i : i + n] for i in range(max(len(t) - n + 1, 1))}


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def term_form_ok(item: dict, concept: dict) -> bool:
    q = item["question_ko"]
    en_terms = [concept["canonical_term"], *concept.get("aliases_en", [])]
    abbrs = concept.get("abbreviations", [])
    has_en = any(t.lower() in q.lower() for t in en_terms if t)
    has_abbr = any(re.search(rf"(?<![A-Za-z]){re.escape(a)}(?![A-Za-z])", q) for a in abbrs)
    has_ko = bool(concept.get("ko_name")) and concept["ko_name"] in q
    form = item["term_form"]
    if form == "ko":
        return has_ko and not LATIN_WORD.search(q.replace(concept.get("ko_name", ""), ""))
    if form == "en":
        return has_en or has_abbr
    if form == "abbr":
        return has_abbr or bool(re.search(r"\b[A-Z]{2,}\b", q))
    return True  # mixed: free form


def main(argv=None) -> Path:
    concepts = {
        c["concept_id"]: c
        for c in json.loads(
            (REPO_ROOT / "data_private/knowledge/concept_map.json").read_text(encoding="utf-8")
        )["concepts"]
    }
    plan = json.loads((EVAL / "plan_v1.json").read_text(encoding="utf-8"))
    slots = {s["slot_id"]: s for s in plan["slots"]}

    items = []
    for f in sorted((EVAL / "draft").glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                items.append(json.loads(line))

    seen_ids, problems = set(), Counter()
    grams = {}
    for it in items:
        checks = {}
        missing = [k for k in REQUIRED if k not in it]
        checks["schema"] = not missing
        slot = slots.get(it.get("slot_id"))
        checks["slot_match"] = bool(slot) and all(
            it.get(k) == slot[k] for k in ("split", "concept_id", "question_type", "term_form")
        )
        checks["unique_id"] = it.get("item_id") not in seen_ids
        seen_ids.add(it.get("item_id"))
        ref = it.get("reference_answer_ko", "")
        checks["ref_words"] = 0 < word_count(ref) <= 30
        checks["ref_sentences"] = 1 <= sentence_count(ref) <= 2
        checks["korean"] = bool(HANGUL.search(it.get("question_ko", ""))) and bool(
            HANGUL.search(ref)
        )
        concept = concepts.get(it.get("concept_id"), {})
        checks["term_form"] = term_form_ok(it, concept) if concept else False
        # answer leakage: overlap of question with reference beyond the concept name itself
        q = it.get("question_ko", "")
        names = [concept.get("canonical_term", ""), concept.get("ko_name", "")]
        q_core, r_core = q, ref
        for n in names:
            if n:
                q_core, r_core = q_core.replace(n, ""), r_core.replace(n, "")
        overlap = len(ngrams(q_core) & ngrams(r_core)) / max(len(ngrams(r_core)), 1)
        checks["no_leak"] = overlap < LEAK_THRESHOLD
        checks["key_points"] = 1 <= len(it.get("key_points_ko", [])) <= 3
        grams[it.get("item_id")] = ngrams(q)
        it["auto_checks"] = checks
        it["leak_overlap"] = round(overlap, 3)

    # near-duplicate questions within the same split
    by_split = defaultdict(list)
    for it in items:
        by_split[it.get("split")].append(it)
    for group in by_split.values():
        for i, a in enumerate(group):
            dup_of = None
            for b in group[:i]:
                if jaccard(grams[a["item_id"]], grams[b["item_id"]]) >= DUP_THRESHOLD:
                    if a.get("variant_group") and a.get("variant_group") == b.get("variant_group"):
                        continue  # term-form variants are expected to be similar
                    dup_of = b["item_id"]
                    break
            a["auto_checks"]["not_duplicate"] = dup_of is None
            a["duplicate_of"] = dup_of

    for it in items:
        failed = [k for k, ok in it["auto_checks"].items() if not ok]
        it["status"] = "auto_ok" if not failed else "needs_review"
        it["failed_checks"] = failed
        problems.update(failed)

    covered = {it["slot_id"] for it in items}
    missing_slots = sorted(set(slots) - covered)
    out = EVAL / "filtered_v1.jsonl"
    out.write_text(
        "".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items), encoding="utf-8"
    )
    summary = {
        "items": len(items),
        "slots": len(slots),
        "missing_slots": len(missing_slots),
        "status": Counter(i["status"] for i in items),
        "failed_checks": problems,
        "by_split": Counter(i.get("split") for i in items),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if missing_slots:
        print("missing slots (first 20):", missing_slots[:20])
    return out


if __name__ == "__main__":
    main()
