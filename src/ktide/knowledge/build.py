"""Build a source-linked concept map from private editorial inputs."""

import argparse
import csv
import json
import random
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from ktide.knowledge.coverage import coverage_stats, depth, facet_files, required_facets
from ktide.knowledge.extract import write_json

DOMAINS = dict(
    enumerate(
        (
            "D01_preprocessing",
            "D02_ngram_lm",
            "D03_classification_eval",
            "D04_neural_training",
            "D05_embedding",
            "D06_sequence_labeling",
            "D07_attention_transformer",
            "D08_pretrained_models",
            "D09_llm_training_use",
            "D10_efficiency",
        ),
        1,
    )
)
FACETS = ("definition", "mechanism", "purpose", "advantages", "limitations", "formula")


def rows(path):
    with path.open(encoding="utf-8", newline="") as stream:
        yield from csv.reader(
            (line for line in stream if line.strip() and not line.startswith("#")),
            delimiter="|",
            quoting=csv.QUOTE_NONE,
        )


def normalized(text):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()


def term_pattern(term):
    term = normalized(term)
    left = r"(?<![a-z0-9])" if term[0].isascii() else ""
    right = r"(?![a-z0-9])" if term[-1].isascii() else ""
    return left + re.escape(term) + right


def build(root, model, reasoning):
    path = root / "data_private/knowledge"

    def read(filename):
        return json.loads(filename.read_text(encoding="utf-8"))

    baseline = read(path / "concept_map.p2b.json")
    if baseline["schema_version"] != 1:
        raise ValueError("P2b backup must use schema 1")
    extracted = root / "data_private/extracted"
    queue = read(extracted / "visual_queue.json")["pages"]
    identity = lambda record: (record["source"]["file"], record["source"]["page"])  # noqa: E731
    selected = {identity(item): item for item in queue}
    with (extracted / "visual_transcripts.jsonl").open(encoding="utf-8") as stream:
        transcripts = {}
        for line in stream:
            record = json.loads(line)
            key = identity(record)
            if (
                key in transcripts
                or key not in selected
                or record["sha256"] != selected[key]["sha256"]
                or record["method"] != "visual_read"
                or record["confidence"] not in {"high", "medium", "low"}
            ):
                raise ValueError(f"Invalid visual record: {key}")
            transcripts[key] = record
    pages = read(path / "lecture_pages.json")
    digests = {page["source"]["file"]: page["sha256"] for page in pages}
    source_index = {(p["source"]["file"], p["source"]["page"]): p for p in pages}
    filenames = sorted({file for file, _ in source_index})
    page_text = [
        (
            page["source"],
            normalized(
                page["text"]
                + " "
                + transcripts.get(
                    identity(page),
                    {},
                ).get("transcript", "")
            ),
        )
        for page in pages
    ]

    def find_page(prefix, number):
        matching = [file for file in filenames if Path(file).name.startswith(prefix)]
        if len(matching) != 1:
            raise ValueError(f"Nonunique PDF reference: {prefix}")
        return source_index[matching[0], int(number)]

    editorial = defaultdict(dict)
    for concept, facet, prefix, number, text in rows(path / "facets.tsv"):
        page = find_page(prefix, number)
        if not page["text"] or facet in editorial[concept]:
            raise ValueError(f"Empty or repeated evidence: {concept} {facet}")
        editorial[concept][facet] = {
            "text_ko": text,
            "status": "stated",
            "evidence": "text_layer",
            "sources": [{**page["source"], "evidence": "text_layer"}],
            "alternatives": [],
        }
    for concept, facet, prefix, number in rows(path / "figures.tsv"):
        page = find_page(prefix, number)
        if facet in editorial[concept]:
            raise ValueError(f"Repeated evidence: {concept} {facet}")
        editorial[concept][facet] = {
            "text_ko": None,
            "status": "figure_only",
            "evidence": "visual_read",
            "sources": [{**page["source"], "evidence": "visual_read"}],
            "alternatives": [],
        }

    changed_facets = set()
    for concept, facet, status, method, prefix, number, text in rows(path / "facets_p2c.tsv"):
        page = find_page(prefix, number)
        if method == "visual_read" and identity(page) not in transcripts:
            raise ValueError(f"Visual facet has no transcription: {concept} {facet}")
        if method == "text_layer" and not page["text"]:
            raise ValueError(f"Missing text evidence: {concept} {facet}")
        source = {**page["source"], "evidence": method}
        previous = editorial[concept].get(facet)
        if (concept, facet) not in changed_facets:
            original_sources = (
                previous["sources"] if previous and previous["text_ko"] == text else []
            )
            editorial[concept][facet] = {
                "text_ko": text,
                "status": status,
                "evidence": method,
                "sources": list(original_sources),
                "alternatives": [],
            }
            changed_facets.add((concept, facet))
        record = editorial[concept][facet]
        if text == record["text_ko"]:
            if source not in record["sources"]:
                record["sources"].append(source)
        else:
            record["alternatives"].append({"text_ko": text, "sources": [source]})
        methods = {s["evidence"] for s in record["sources"]}
        methods.update(s["evidence"] for a in record["alternatives"] for s in a["sources"])
        record["evidence"] = "both" if len(methods) > 1 else next(iter(methods))

    reviewed_roles = defaultdict(list)
    for concept, prefix, number, role in rows(path / "substantive_p2c.tsv"):
        page = find_page(prefix, number)
        reviewed_roles[concept].append({**page["source"], "role": role})

    concepts = {}
    unresolved = {}
    for concept, term, korean, domain, alias_field, parent in rows(path / "concepts.tsv"):
        aliases = list(dict.fromkeys(x for x in alias_field.split(",") if x and x != term))
        spellings = [term, *aliases]
        if korean != term:
            spellings.append(korean)
        flags = 0 if term == "ZeRO" else re.IGNORECASE
        pattern = re.compile("|".join(map(term_pattern, spellings)), flags)
        if term == "Recall":
            pattern = re.compile(r"precision.{0,24}recall|recall\s*=|재현율", re.IGNORECASE)
        mentions = [source for source, text in page_text if pattern.search(text)]
        evidence = editorial.get(concept, {})
        if not mentions and not evidence:
            unresolved[concept] = term
            continue
        facets = {
            facet: evidence.get(
                facet,
                {
                    "text_ko": None,
                    "status": "missing",
                    "evidence": None,
                    "sources": [],
                    "alternatives": [],
                },
            )
            for facet in FACETS
        }
        sources = {(s["file"], s["page"], "mention") for s in mentions}
        for facet, record in evidence.items():
            role = "figure" if record["status"] == "figure_only" else "mechanism"
            if facet in {"definition", "formula"} and record["status"] != "figure_only":
                role = facet
            source_rows = record["sources"] + [
                s for alternative in record["alternatives"] for s in alternative["sources"]
            ]
            sources.update((s["file"], s["page"], role) for s in source_rows)
        sources.update((s["file"], s["page"], s["role"]) for s in reviewed_roles[concept])
        lecture_sources = [
            {"file": file, "page": page, "role": role} for file, page, role in sorted(sources)
        ]
        stats = coverage_stats(lecture_sources, digests)
        concepts[concept] = {
            "concept_id": concept,
            "canonical_term": term,
            "ko_name": korean,
            "aliases_ko": [x for x in aliases if re.search("[가-힣]", x)],
            "aliases_en": [x for x in aliases if x != korean and not re.search("[가-힣]", x)],
            "abbreviations": [x for x in spellings if re.fullmatch(r"[A-Z][A-Z0-9-]{1,7}", x)],
            "preserve_english": bool(re.search("[a-zA-Z]", term)),
            "domain": DOMAINS[int(domain)],
            "parent_id": parent or None,
            "related_ids": [],
            "coverage_depth": depth(stats),
            "coverage_stats": stats,
            "facets": facets,
            "lecture_sources": lecture_sources,
            "notes": "",
        }

        item = concepts[concept]
        missing = required_facets(item)
        reason = ""
        if missing:
            reason = "검토한 강의 근거에서 보완 항목 확인 필요: " + ", ".join(missing)
        elif item["coverage_depth"] == "mention_only":
            reason = "강의 표기를 확인했으며 실질 설명의 출처는 미확인"
        item["enrichment_needed"] = {"needed": bool(reason), "reason": reason}

    if set(editorial) - concepts.keys():
        raise ValueError("Editorial input references an unknown concept")

    for item in concepts.values():
        parent = item["parent_id"]
        if parent in concepts:
            concepts[parent]["related_ids"].append(item["concept_id"])
        elif parent:
            item["parent_id"] = None
    for left, right in rows(path / "relationships.tsv"):
        for item, related in ((left, right), (right, left)):
            if related not in concepts[item]["related_ids"]:
                concepts[item]["related_ids"].append(related)
    terms = read(root / "data_private/audit/concepts.json")
    term_ids = dict(rows(path / "terms_mapping.tsv"))
    mapping = {}
    for row in terms:
        term = row["concept"]
        identifier = term_ids[term]
        mapping[term] = (
            {"concept_id": identifier}
            if identifier in concepts
            else {"reason": "제외 반영 후 강의 텍스트에서 뒷받침되는 표기 또는 설명 미확인"}
        )
    questions = {number: ids.split(",") for number, ids in rows(path / "question_mapping.tsv")}
    if set(questions) != set(map(str, range(1, 12))):
        raise ValueError("Public question mapping must include all 11 question numbers")
    if any(identifier not in concepts for ids in questions.values() for identifier in ids):
        raise ValueError("Public question references an unknown concept")
    backed = facet_files(concepts.values())
    extraction = read(path / "extraction_files.json")
    zero = [
        {
            "file": row["file"],
            "reason": (
                "동일 SHA-256 파일의 추출 결과를 재사용함"
                if row.get("reason") == "duplicate_sha256"
                else "확인된 facet 근거 없음. 텍스트와 미판독 이미지 추가 검토 필요"
            ),
        }
        for row in extraction
        if row["file"] not in backed
    ]
    previous_ids = {item["concept_id"] for item in baseline["concepts"]}
    checks = {
        "terms_mapping": mapping,
        "public_question_coverage": questions,
        "files_processed": extraction,
        "zero_facet_files": zero,
        "visual_read_summary": {
            "selected_pages": len(queue),
            "read_pages": len(transcripts),
            "confidence": dict(Counter(t["confidence"] for t in transcripts.values())),
            "unreadable_pages": [t["source"] for t in transcripts.values() if t["unreadable"]],
            "pending_pages": [
                item["source"] for key, item in selected.items() if key not in transcripts
            ],
        },
        "added_concepts": sorted(concepts.keys() - previous_ids),
        "rejected_candidates": [
            {"concept_id": key, "reason": reason} for key, reason in rows(path / "rejected_p2c.tsv")
        ],
        "open_issues": [
            {"issue": "강의 텍스트 및 현재 판독본에 근거가 없는 후보", "candidates": unresolved},
            {
                "issue": "필수 facet 근거 미확인",
                "concepts": [
                    {"concept_id": k, "reason": v["enrichment_needed"]["reason"]}
                    for k, v in concepts.items()
                    if required_facets(v)
                ],
            },
            {
                "issue": "핵심 후보의 실질 근거 페이지 추가 확인 필요",
                "concept_ids": [
                    k
                    for k in ("quantization", "zero_optimizer", "ppo", "t5")
                    if concepts[k]["coverage_depth"] != "core"
                ],
            },
            {"issue": "미판독 선택 페이지 남음", "count": len(queue) - len(transcripts)},
            {"issue": "실질 설명 통계는 확인한 페이지에 한정되며 단순 언급은 문자열 후보임"},
        ],
    }
    sample = [
        {
            "concept_id": id_,
            "facet": name,
            "text_ko": facet["text_ko"],
            "sources": facet["sources"],
            "evidence": facet["evidence"],
        }
        for id_, item in concepts.items()
        for name, facet in item["facets"].items()
        if facet["status"] in {"partial", "stated"}
    ]
    seed = 20261125
    write_json(
        path / "review_sample_p2c.json",
        {
            "seed": seed,
            "facets": random.Random(seed).sample(sample, 20),
        },
    )
    write_json(path / "concept_map_checks.json", checks)
    write_json(
        path / "concept_map.json",
        {
            "schema_version": 2,
            "created_by": {"tool": "codex", "model": model, "reasoning": reasoning},
            "concepts": list(concepts.values()),
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--model", required=True)
    parser.add_argument("--reasoning", required=True)
    args = parser.parse_args()
    build(args.root.resolve(), args.model, args.reasoning)


if __name__ == "__main__":
    main()
