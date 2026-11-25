"""Map human-written evaluation items to concepts automatically.

The user writes only a question and an answer. Each item without a concept_id is matched against the
concept map by term occurrence in the question (then the answer): canonical term, Korean name,
aliases and abbreviations, preferring the longest match. Items with no match or a tie are marked
`mapping: "needs_review"` so they can be assigned by hand.

Used by `python -m ktide.evalset.review import`; can also be run alone to preview:
    uv run python -m ktide.evalset.map_human
"""

from __future__ import annotations

import json
import re

from ktide.professor import REPO_ROOT

EVAL = REPO_ROOT / "data_private" / "evalset"


def load_terms():
    concepts = json.loads(
        (REPO_ROOT / "data_private/knowledge/concept_map.json").read_text(encoding="utf-8")
    )["concepts"]
    plan = json.loads((EVAL / "plan_v1.json").read_text(encoding="utf-8"))
    unseen = set(plan.get("unseen_concepts", []))
    terms = []
    for c in concepts:
        forms = {c["canonical_term"], c.get("ko_name") or ""}
        forms |= set(c.get("aliases_en", [])) | set(c.get("aliases_ko", []))
        forms |= set(c.get("abbreviations", []))
        for f in forms:
            f = f.strip()
            if len(f) >= 2:
                terms.append((f, c["concept_id"]))
    terms.sort(key=lambda t: -len(t[0]))
    return terms, unseen


def find(text: str, terms) -> list[tuple[str, str]]:
    hits = []
    for form, cid in terms:
        if form.isascii():
            pat = rf"(?<![A-Za-z0-9]){re.escape(form)}(?![A-Za-z0-9])"
            if re.search(pat, text, flags=re.IGNORECASE):
                hits.append((form, cid))
        elif form in text:
            hits.append((form, cid))
    return hits


def map_items(items: list[dict]) -> list[dict]:
    terms, unseen = load_terms()
    for it in items:
        if it.get("concept_id"):
            it["mapping"] = "user"
            continue
        for field in ("question_ko", "reference_answer_ko"):
            hits = find(it[field], terms)
            if hits:
                best_len = len(hits[0][0])
                best = sorted({cid for form, cid in hits if len(form) == best_len})
                if len(best) == 1:
                    it["concept_id"] = best[0]
                    it["mapping"] = f"auto:{field}"
                else:
                    it["mapping"] = "needs_review"
                    it["mapping_candidates"] = best
                break
        else:
            it["mapping"] = "needs_review"
            it["mapping_candidates"] = []
        if it.get("concept_id") in unseen:
            it["mapping_note"] = "unseen concept: exclude from seen/unseen comparisons or move"
    return items


def main():
    path = EVAL / "review" / "human_items_v1.json"
    items = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    mapped = map_items([dict(i) for i in items])
    for m in mapped:
        print(m["id"], m.get("concept_id"), m["mapping"], m.get("mapping_candidates", ""))
    print(
        f"{len(mapped)} items, needs_review: {sum(m['mapping'] == 'needs_review' for m in mapped)}"
    )


if __name__ == "__main__":
    main()
