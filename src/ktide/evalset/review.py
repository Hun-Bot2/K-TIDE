"""Human review round-trip for evaluation items (docs/research/evaluation_protocol.md).

export: writes data_private/evalset/review/review_sheet_v1.csv (test_seen + test_unseen items) and
        human_items_template.csv (for the user's own 30–50 questions, test_seen concepts only).
import: reads the edited CSVs and writes data_private/evalset/reviewed_v1.jsonl and human_v1.jsonl.

The CSVs are UTF-8 with BOM so they open correctly in Excel/Numbers/Google Sheets.

Review columns to fill: decision = accept | edit | reject; edited_question / edited_answer only when
decision is edit; note = free text (reason for edit or reject).

Usage:
    uv run python -m ktide.evalset.review export
    uv run python -m ktide.evalset.review import
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter

from ktide.evalset.map_human import map_items
from ktide.metrics import sentence_count, word_count
from ktide.professor import REPO_ROOT

EVAL = REPO_ROOT / "data_private" / "evalset"
REVIEW = EVAL / "review"
SHEET = REVIEW / "review_sheet_v1.csv"
HUMAN = REVIEW / "human_items_template.csv"
COLS = [
    "item_id",
    "split",
    "domain",
    "concept",
    "question_type",
    "term_form",
    "variant_group",
    "question_ko",
    "reference_answer_ko",
    "key_points_ko",
    "auto_flags",
    "writer_notes",
    "decision",
    "edited_question",
    "edited_answer",
    "note",
]
HUMAN_COLS = [
    "concept_id",
    "concept",
    "question_ko",
    "reference_answer_ko",
    "key_points_ko",
    "note",
]


def read_jsonl(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def export():
    items = read_jsonl(EVAL / "filtered_v1.jsonl")
    concepts = {
        c["concept_id"]: c
        for c in json.loads(
            (REPO_ROOT / "data_private/knowledge/concept_map.json").read_text(encoding="utf-8")
        )["concepts"]
    }
    REVIEW.mkdir(parents=True, exist_ok=True)
    rows = [i for i in items if i["split"] in ("test_seen", "test_unseen")]
    rows.sort(key=lambda i: (i["split"], i["domain"], i["concept_id"], i["item_id"]))
    with SHEET.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for i in rows:
            c = concepts[i["concept_id"]]
            w.writerow(
                {
                    "item_id": i["item_id"],
                    "split": i["split"],
                    "domain": i["domain"][:3],
                    "concept": f"{c['canonical_term']} / {c.get('ko_name', '')}",
                    "question_type": i["question_type"],
                    "term_form": i["term_form"],
                    "variant_group": i.get("variant_group") or "",
                    "question_ko": i["question_ko"],
                    "reference_answer_ko": i["reference_answer_ko"],
                    "key_points_ko": " | ".join(i.get("key_points_ko", [])),
                    "auto_flags": ",".join(i.get("failed_checks", [])),
                    "writer_notes": i.get("writer_notes", ""),
                    "decision": "",
                    "edited_question": "",
                    "edited_answer": "",
                    "note": "",
                }
            )
    seen = sorted({i["concept_id"] for i in items if i["split"] == "test_seen"})
    with HUMAN.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HUMAN_COLS)
        w.writeheader()
        for cid in seen:
            c = concepts[cid]
            w.writerow(
                {
                    "concept_id": cid,
                    "concept": f"{c['canonical_term']} / {c.get('ko_name', '')}",
                    "question_ko": "",
                    "reference_answer_ko": "",
                    "key_points_ko": "",
                    "note": "",
                }
            )
    print(f"review sheet: {len(rows)} items -> {SHEET}")
    print(f"human template: {len(seen)} concepts (fill 30–50 rows, delete the rest) -> {HUMAN}")


WEB_DECISIONS = REVIEW / "decisions_v1.json"
WEB_HUMAN = REVIEW / "human_items_v1.json"


def decision_rows():
    """Rows from the web labeler (preferred) or the CSV sheet."""
    if WEB_DECISIONS.exists():
        data = json.loads(WEB_DECISIONS.read_text(encoding="utf-8"))
        for iid, d in data.items():
            yield {
                "item_id": iid,
                "decision": d.get("decision") or "",
                "note": d.get("note", ""),
                "edited_question": d.get("edited_question", ""),
                "edited_answer": d.get("edited_answer", ""),
            }
        return
    with SHEET.open(encoding="utf-8-sig", newline="") as f:
        yield from csv.DictReader(f)


def human_rows():
    if WEB_HUMAN.exists():
        for h in json.loads(WEB_HUMAN.read_text(encoding="utf-8")):
            yield {
                "concept_id": h["concept_id"],
                "question_ko": h["question_ko"],
                "reference_answer_ko": h["reference_answer_ko"],
                "key_points_ko": " | ".join(h.get("key_points_ko", [])),
            }
        return
    if HUMAN.exists():
        with HUMAN.open(encoding="utf-8-sig", newline="") as f:
            yield from csv.DictReader(f)


def import_():
    items = {i["item_id"]: i for i in read_jsonl(EVAL / "filtered_v1.jsonl")}
    decided, problems = Counter(), []
    reviewable = {k for k, v in items.items() if v["split"] in ("test_seen", "test_unseen")}
    seen_rows = set()
    for row in decision_rows():
        seen_rows.add(row["item_id"])
        it = items[row["item_id"]]
        d = row["decision"].strip().lower()
        if d not in ("accept", "edit", "reject"):
            problems.append((row["item_id"], "no decision"))
            continue
        it["human_review"] = {"decision": d, "note": row["note"].strip()}
        if d == "edit":
            if row["edited_question"].strip():
                it["question_original"], it["question_ko"] = (
                    it["question_ko"],
                    row["edited_question"].strip(),
                )
            if row["edited_answer"].strip():
                it["reference_original"] = it["reference_answer_ko"]
                it["reference_answer_ko"] = row["edited_answer"].strip()
        ref = it["reference_answer_ko"]
        if d != "reject" and not (word_count(ref) <= 30 and 1 <= sentence_count(ref) <= 2):
            problems.append((row["item_id"], "reference exceeds 30 words or 2 sentences"))
        it["status"] = {
            "accept": "human_accepted",
            "edit": "human_edited",
            "reject": "rejected",
        }[d]
        decided[d] += 1
    # Second pass: cross-model answerability recheck (applies to any split, after the first review).
    recheck_path = REVIEW / "recheck_v1.json"
    adjudication = (
        {a["item_id"]: a for a in read_jsonl(EVAL / "answerability_adjudication_v1.jsonl")}
        if (EVAL / "answerability_adjudication_v1.jsonl").exists()
        else {}
    )
    rechecked = Counter()
    if recheck_path.exists():
        for iid, rc in json.loads(recheck_path.read_text(encoding="utf-8")).items():
            it, adj = items.get(iid), adjudication.get(iid, {})
            if not it:
                continue
            action = rc.get("action")
            new_q = new_a = None
            if action == "apply":
                new_q, new_a = adj.get("suggested_question_ko"), adj.get("suggested_answer_ko")
            elif action == "edit":
                new_q, new_a = rc.get("edited_question") or None, rc.get("edited_answer") or None
            if new_q and new_q != it["question_ko"]:
                it.setdefault("question_original", it["question_ko"])
                it["question_ko"] = new_q
            if new_a and new_a != it["reference_answer_ko"]:
                it.setdefault("reference_original", it["reference_answer_ko"])
                it["reference_answer_ko"] = new_a
            if action == "reject":
                it["status"] = "rejected"
            elif new_q or new_a:
                it["status"] = "human_edited"
            it["answerability_recheck"] = {
                "category": adj.get("category"),
                "action": action,
                "note": rc.get("note", ""),
            }
            ref = it["reference_answer_ko"]
            if action != "reject" and not (word_count(ref) <= 30 and 1 <= sentence_count(ref) <= 2):
                problems.append((iid, "rechecked reference exceeds 30 words or 2 sentences"))
            rechecked[action] += 1
    undecided = sorted(reviewable - seen_rows)
    if undecided:
        problems.append((f"{len(undecided)} items", "not reviewed yet"))
    out = EVAL / "reviewed_v1.jsonl"
    out.write_text(
        "".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items.values()), encoding="utf-8"
    )
    human = []
    for n, row in enumerate(human_rows(), 1):
        if not (row["question_ko"].strip() and row["reference_answer_ko"].strip()):
            continue
        human.append(
            {
                "item_id": f"human-{n:04d}",
                "split": "human",
                "concept_id": row.get("concept_id") or None,
                "question_ko": row["question_ko"].strip(),
                "reference_answer_ko": row["reference_answer_ko"].strip(),
                "key_points_ko": [
                    k.strip() for k in (row.get("key_points_ko") or "").split("|") if k.strip()
                ],
                "writer": {"tool": "human"},
                "status": "human_written",
            }
        )
    human = map_items(human)
    needs_mapping = [h["item_id"] for h in human if h.get("mapping") == "needs_review"]
    if needs_mapping:
        problems.append((needs_mapping, "human items need a concept assigned by hand"))
    (EVAL / "human_v1.jsonl").write_text(
        "".join(json.dumps(i, ensure_ascii=False) + "\n" for i in human), encoding="utf-8"
    )
    print(
        {
            "decisions": dict(decided),
            "recheck": dict(rechecked),
            "human_items": len(human),
            "problems": problems[:20],
            "n_problems": len(problems),
        }
    )


if __name__ == "__main__":
    {"export": export, "import": import_}[sys.argv[1]]()
