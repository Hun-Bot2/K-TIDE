"""Assemble, validate, and count privately authored canonical knowledge units."""

import argparse
import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from statistics import mean

from ktide.audit.filter_corpus import identity, write_jsonl
from ktide.knowledge.build import rows
from ktide.knowledge.extract import write_json
from ktide.knowledge.visual import load
from ktide.metrics import sentence_count, word_count

FIELDS = (
    "core_answer_ko",
    "definition_ko",
    "mechanism_ko",
    "purpose_ko",
    "limitations_ko",
    "misconceptions_ko",
    "contrast_with",
    "formula",
    "terminology",
    "lecture_alignment",
)
BASIS = {"lecture", "external_reference", "model_knowledge", "slp_textbook"}


def read_jsonl(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def validate(units, concepts, allowed, complete=True):
    ids = Counter(row["concept_id"] for row in units)
    assert all(count == 1 and key in concepts for key, count in ids.items())
    if complete:
        assert ids.keys() == concepts.keys()
    for row in units:
        assert {
            "concept_id",
            "provenance",
            "writer",
            "basis",
            "sources",
            "confidence",
            "open_questions",
            *FIELDS,
        } <= row.keys()
        assert row["provenance"] == "llm_teacher"
        assert 1 <= word_count(row["core_answer_ko"]) <= 30
        assert 1 <= sentence_count(row["core_answer_ko"]) <= 2
        assert 2 <= sentence_count(row["definition_ko"]) <= 3
        assert len(row["misconceptions_ko"]) <= 3
        assert {target["concept_id"] for target in row["contrast_with"]} <= concepts.keys()
        assert all((s["file"], s["page"]) in allowed for s in row["sources"]["lecture"])
        assert row["basis"].keys() == set(FIELDS)
        assert row["purpose_ko"]
        for field, grounds in row["basis"].items():
            assert field in FIELDS and set(grounds) <= BASIS
            if "external_reference" in grounds:
                assert row["sources"]["external"]
        assert row["confidence"]["level"] in {"high", "medium", "low"}


def build(root, model, reasoning, write_date):
    data = root / "data_private"
    private = data / "knowledge"
    concepts = {r["concept_id"]: r for r in load(private / "concept_map.json")["concepts"]}
    corpus = load(data / "audit/corpus_v2.json")["pages"]
    allowed = {identity(row) for row in corpus}

    def allowed_source(source):
        return (source["file"], source["page"]) in allowed

    visual = defaultdict(list)
    for row in read_jsonl(data / "extracted/visual_terms.jsonl"):
        assert identity(row) in allowed
        for item in row["concepts"]:
            if item["concept_id"] in concepts:
                visual[item["concept_id"]].append((row["source"], item["emphasis"]))

    supplements = load(private / "cku_editorial.json")
    external = defaultdict(list)
    for item, field, title, section, url in rows(private / "cku_references.tsv"):
        external[item].append((field, {"title": title, "section": section, "url": url}))
    units = []
    ordered = sorted(
        concepts.values(), key=lambda row: (row["coverage_depth"] != "core", row["domain"])
    )
    authored = {}
    for key, *values in rows(private / "cku_text.tsv"):
        if key in authored or key not in concepts:
            raise ValueError(f"Unknown or repeated CKU: {key}")
        authored[key] = values
    for concept in ordered:
        key = concept["concept_id"]
        if key not in authored:
            continue
        core, detail, mechanism, purpose, limit = authored[key]
        extra = supplements.get(key, {})
        facets = [
            facet
            for facet in concept["facets"].values()
            if facet["text_ko"] and any(map(allowed_source, facet["sources"]))
        ]
        sources = {
            (s["file"], s["page"])
            for facet in facets
            for s in facet["sources"]
            if allowed_source(s)
        }
        sources.update((s["file"], s["page"]) for s, _ in visual[key])
        if not sources:
            sources = {
                (s["file"], s["page"]) for s in concept["lecture_sources"] if allowed_source(s)
            }
        evidence = [f["text_ko"] for f in facets] or [summary for _, summary in visual[key]]
        alignment = extra.get("alignment", {})
        difference = alignment.get("difference_note")
        questions = list(extra.get("open_questions", []))
        if not evidence:
            questions.append("강의에서 개념을 직접 설명한 범위와 표기를 확인해 주세요.")
        if not sources:
            questions.append("v2 코퍼스에서 이 개념을 뒷받침하는 출처를 확인해 주세요.")
        aliases = concept["aliases_en"]
        full = extra.get("full_form")
        row = {
            "concept_id": key,
            "provenance": "llm_teacher",
            "writer": {"tool": "codex", "model": model, "reasoning": reasoning, "date": write_date},
            "core_answer_ko": core,
            "definition_ko": f"{core} {detail}",
            "mechanism_ko": mechanism or None,
            "purpose_ko": purpose,
            "limitations_ko": limit or None,
            "misconceptions_ko": extra.get("misconceptions", []),
            "contrast_with": extra.get("contrasts", []),
            "formula": extra.get("formula"),
            "terminology": {
                "canonical_term": concept["canonical_term"],
                "full_form": full,
                "preserve_english": concept["preserve_english"],
                "aliases_ko": concept["aliases_ko"],
                "aliases_en": aliases,
            },
            "lecture_alignment": {
                "consistent": alignment.get("consistent", True),
                "lecture_summary": " ".join(evidence[:3]) or None,
                "difference_note": difference,
                "status": "reviewed_evidence" if evidence else "scope_unverified",
            },
            "sources": {
                "lecture": [{"file": f, "page": p} for f, p in sorted(sources)],
                "external": [ref for _, ref in external[key]],
            },
            "confidence": {
                "level": extra.get(
                    "confidence", "high" if evidence else "medium" if sources else "low"
                ),
                "reason": extra.get("confidence_reason", "" if evidence else "강의 설명 근거 부족"),
            },
            "open_questions": questions,
        }
        row["basis"] = {f: ["model_knowledge"] if row[f] else [] for f in FIELDS}
        row["basis"]["terminology"] = ["model_knowledge"] + (["lecture"] if sources else [])
        row["basis"]["lecture_alignment"] = ["lecture"] if evidence else []
        if evidence:
            for field in extra.get("lecture_fields", []):
                row["basis"][field].append("lecture")
        for field, _ in external[key]:
            row["basis"][field].append("external_reference")
        units.append(row)
    validate(units, concepts, allowed, complete=False)
    write_jsonl(private / "cku_v1.jsonl", units)
    pending = [row["concept_id"] for row in ordered if row["concept_id"] not in authored]
    write_json(
        private / "cku_progress.json",
        {
            "total": len(concepts),
            "completed": len(units),
            "pending": pending,
            "last": units[-1]["concept_id"] if units else None,
        },
    )
    return units, concepts


def statistics(units, concepts, visual_count, added_count):
    return {
        "total": len(units),
        "domains": Counter(concepts[row["concept_id"]]["domain"].split("_")[0] for row in units),
        "basis": Counter(b for row in units for values in row["basis"].values() for b in values),
        "confidence": Counter(row["confidence"]["level"] for row in units),
        "discordant": sum(not row["lecture_alignment"]["consistent"] for row in units),
        "average_words": round(mean(word_count(row["core_answer_ko"]) for row in units), 2)
        if units
        else 0,
        "visual_pages": visual_count,
        "new_concepts": added_count,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--model", required=True)
    parser.add_argument("--reasoning", required=True)
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args()
    units, concepts = build(args.root, args.model, args.reasoning, args.date)
    visual_count = len(read_jsonl(args.root / "data_private/extracted/visual_terms.jsonl"))
    new_path = args.root / "data_private/knowledge/cku_v1_new_concepts.json"
    added_count = len(load(new_path)["added"]) if new_path.exists() else 0
    print(json.dumps(statistics(units, concepts, visual_count, added_count), ensure_ascii=False))


if __name__ == "__main__":
    main()
