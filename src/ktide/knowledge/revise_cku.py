"""Apply private, reviewed editorial decisions and write an inspectable CKU revision."""

import argparse
import copy
import json
import re
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path
from statistics import mean

from ktide.audit.filter_corpus import write_jsonl
from ktide.knowledge.cku import read_jsonl, validate
from ktide.knowledge.extract import write_json
from ktide.knowledge.visual import load
from ktide.metrics import word_count


def source_key(source):
    return unicodedata.normalize("NFC", source["file"]), source["page"]


def set_field(row, field, value):
    parts = field.split(".")
    target = row
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = copy.deepcopy(value)


def review_items(review):
    items = [("issue", str(i), text) for i, text in enumerate(review["issues"])]
    if review["lecture_difference"]:
        items.append(("lecture_difference", "lecture_difference", review["lecture_difference"]))
    if review["suggested_core_answer_ko"]:
        items.append(("suggestion", "core_answer_ko", review["suggested_core_answer_ko"]))
    items.extend(("suggestion", field, value) for field, value in review["suggested_fixes"].items())
    items.extend(
        ("misconception", str(i), text)
        for i, text in enumerate(review["suggested_misconceptions_ko"])
    )
    items.extend(
        ("contrast", item["concept_id"], item["difference_ko"])
        for item in review["suggested_contrast_with"]
    )
    return items


def revise(root, model, reasoning):
    private = root / "data_private"
    directory = private / "knowledge"
    review_dir = directory / "review"
    units = read_jsonl(directory / "cku_v1.jsonl")
    reviews = read_jsonl(review_dir / "cku_review_all.jsonl")
    concept_map = {r["concept_id"]: r for r in load(directory / "concept_map.json")["concepts"]}
    original = {row["concept_id"]: copy.deepcopy(row) for row in units}
    by_id = {row["concept_id"]: row for row in units}
    assert len(by_id) == len(units) == len(reviews)
    assert {r["concept_id"] for r in reviews} == by_id.keys()
    corpus = load(private / "audit/corpus_v2.json")["pages"]
    canonical = {source_key(row["source"]): row["source"] for row in corpus}
    pages = {source_key(r["source"]): r["text"] for r in load(directory / "lecture_pages.json")}
    filters = {
        source_key(row["source"]): row for row in read_jsonl(private / "audit/page_filter.jsonl")
    }

    def resolve(source):
        key = source_key(source)
        if key in canonical:
            return canonical[key]
        row = filters.get(key)
        if row and row["reason"] in {"duplicate", "repeated_slide"} and row["duplicate_of"]:
            return canonical.get(source_key(row["duplicate_of"]))
        return None

    editorial = load(review_dir / "cku_v2_editorial.json")
    decisions = []
    for review in reviews:
        key = review["concept_id"]
        row = by_id[key]
        edits = editorial[key]
        for field, value in edits["changes"].items():
            set_field(row, field, value)
        for text in review["suggested_misconceptions_ko"]:
            if text not in row["misconceptions_ko"] and len(row["misconceptions_ko"]) < 3:
                row["misconceptions_ko"].append(text)
        row["misconceptions_ko"] = edits.get("misconceptions", row["misconceptions_ko"])
        for item in review["suggested_contrast_with"]:
            if item["concept_id"] in by_id and not (
                key == "average_precision" and item["concept_id"] == "map"
            ):
                row["contrast_with"] = [
                    old for old in row["contrast_with"] if old["concept_id"] != item["concept_id"]
                ]
                row["contrast_with"].append(copy.deepcopy(item))
        for item in edits.get("contrasts", []):
            row["contrast_with"] = [
                old for old in row["contrast_with"] if old["concept_id"] != item["concept_id"]
            ] + [copy.deepcopy(item)]
        checked = []
        for source in edits.get("sources", review["checked_pages"]):
            resolved = resolve(source)
            if resolved and resolved not in checked:
                checked.append(resolved)
        # Editorial selection is explicit. It never turns an excluded source into a retained one.
        row["sources"]["lecture"] = checked
        summary = edits.get("lecture_summary")
        if not summary:
            raise ValueError(f"Missing reviewed lecture summary: {key}")
        alignment = row["lecture_alignment"]
        alignment["lecture_summary"] = summary
        alignment["status"] = edits.get("alignment_status", "reviewed_evidence")
        if review["lecture_difference"] and not edits["changes"].get(
            "lecture_alignment.difference_note"
        ):
            alignment["difference_note"] = edits.get("scope_note")
        for ref in edits.get("external", []):
            if ref not in row["sources"]["external"]:
                row["sources"]["external"].append(ref)
        if not checked:
            alignment["status"] = "reviewed_scope_only"
        if "sources" in edits:
            assert len(checked) == len(edits["sources"]), key
        assert all(source_key(s) in pages or s in checked for s in checked)
        row["writer"] = {
            "tool": "codex",
            "model": model,
            "reasoning": reasoning,
            "date": date.today().isoformat(),
        }
        if row["terminology"]["preserve_english"]:
            term = row["terminology"]["canonical_term"]
            if term.casefold() not in row["core_answer_ko"].casefold():
                match = re.match(r"^.+?(?:은|는)\s+", row["core_answer_ko"])
                if not match:
                    raise ValueError(f"Cannot introduce canonical term: {key}")
                row["core_answer_ko"] = term + "은 " + row["core_answer_ko"][match.end() :]
        if (
            row["definition_ko"] == original[key]["definition_ko"]
            and row["core_answer_ko"] != original[key]["core_answer_ko"]
        ):
            old_core = original[key]["core_answer_ko"]
            if not row["definition_ko"].startswith(old_core):
                raise ValueError(f"Definition prefix differs from core: {key}")
            row["definition_ko"] = row["core_answer_ko"] + row["definition_ko"][len(old_core) :]
        if concept_map[key]["coverage_depth"] == "core" and not row["misconceptions_ko"]:
            raise ValueError(f"Core concept lacks misconception: {key}")
        row["open_questions"] = edits.get("open_questions", [])
        row["confidence"] = edits.get(
            "confidence",
            {
                "level": "medium",
                "reason": "Claude 의견을 반영한 작성자 수정본. 재검증 대기.",
            },
        )
        for field in (
            "core_answer_ko",
            "definition_ko",
            "mechanism_ko",
            "purpose_ko",
            "limitations_ko",
            "misconceptions_ko",
            "contrast_with",
            "formula",
        ):
            if row[field] != original[key][field]:
                row["basis"][field] = ["model_knowledge"]
                if checked and field in edits.get("lecture_fields", []):
                    row["basis"][field].append("lecture")
        row["basis"]["lecture_alignment"] = ["lecture"] if checked else ["model_knowledge"]
        row["basis"]["terminology"] = ["model_knowledge"]
        for field in edits.get("external_fields", []):
            if "external_reference" not in row["basis"][field]:
                row["basis"][field].append("external_reference")
        item_decisions = []
        for category, identifier, text in review_items(review):
            entry_id = category + ":" + identifier
            decision = copy.deepcopy(
                edits.get("decisions", {}).get(
                    entry_id,
                    {
                        "decision": "accept",
                        "reason": "근거 대조 후 해당 설명·용어·출처에 반영함.",
                    },
                )
            )
            item_decisions.append({"review_item": entry_id, "issue": text, **decision})
        if not item_decisions:
            item_decisions = [
                {
                    "review_item": "verdict",
                    "issue": "수정 제안 없는 판정",
                    "decision": "accept",
                    "reason": "기존 설명을 유지하고 출처와 메타데이터를 정리함.",
                }
            ]
        decisions.append(
            {
                "concept_id": key,
                "review_verdict": review["verdict"],
                "decisions": item_decisions,
            }
        )

    for row in units:
        for pair in list(row["contrast_with"]):
            other = by_id[pair["concept_id"]]
            reverse = {"concept_id": row["concept_id"], "difference_ko": pair["difference_ko"]}
            existing = next(
                (i for i in other["contrast_with"] if i["concept_id"] == row["concept_id"]), None
            )
            if existing:
                existing["difference_ko"] = pair["difference_ko"]
            else:
                other["contrast_with"].append(reverse)
                other["basis"]["contrast_with"] = ["model_knowledge"]
    diff = []
    for row in units:
        key = row["concept_id"]
        changed = [field for field in original[key] if row[field] != original[key][field]]
        row["version"] = 2
        row["revision"] = {
            "based_on": "cku_v1",
            "review": "cku_review_all",
            "changed_fields": changed,
        }
        next(d for d in decisions if d["concept_id"] == key)["changed_fields"] = changed
        diff.append(
            {
                "concept_id": key,
                "changed_fields": changed,
                "core_answer_before": original[key]["core_answer_ko"],
                "core_answer_after": row["core_answer_ko"],
            }
        )
    allowed = {(s["file"], s["page"]) for s in canonical.values()}
    validate(units, concept_map, allowed)
    write_jsonl(directory / "cku_v2.jsonl", units)
    write_jsonl(review_dir / "cku_v2_decisions.jsonl", decisions)
    write_json(directory / "cku_v2_diff_summary.json", diff)
    metrics = {
        "concepts": len(units),
        "decisions": Counter(d["decision"] for r in decisions for d in r["decisions"]),
        "changed_fields": Counter(field for r in diff for field in r["changed_fields"]),
        "consistent_false": sum(not r["lecture_alignment"]["consistent"] for r in units),
        "lecture_error_note": sum(
            bool(r["lecture_alignment"].get("lecture_error_note")) for r in units
        ),
        "misconceptions_before": sum(bool(r["misconceptions_ko"]) for r in original.values()),
        "misconceptions_after": sum(bool(r["misconceptions_ko"]) for r in units),
        "contrasts_before": sum(bool(r["contrast_with"]) for r in original.values()),
        "contrasts_after": sum(bool(r["contrast_with"]) for r in units),
        "mean_core_words": round(mean(word_count(r["core_answer_ko"]) for r in units), 2),
        "unfilled": {
            field: [r["concept_id"] for r in units if not r[field]]
            for field in ("misconceptions_ko", "contrast_with")
        },
    }
    write_json(review_dir / "cku_v2_stats.json", metrics)
    print(json.dumps({k: v for k, v in metrics.items() if k != "unfilled"}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--model", required=True)
    parser.add_argument("--reasoning", required=True)
    args = parser.parse_args()
    revise(args.root, args.model, args.reasoning)


if __name__ == "__main__":
    main()
