"""Build P2f Teacher units from CKU v2 and locally reviewed lecture evidence."""

import argparse
import re
import unicodedata
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path

from ktide.audit.filter_corpus import identity, write_jsonl
from ktide.knowledge.build import FACETS
from ktide.knowledge.cku import FIELDS, read_jsonl, validate
from ktide.knowledge.coverage import coverage_stats, depth, required_facets
from ktide.knowledge.extract import write_json
from ktide.knowledge.visual import load

TEMPLATE = "강의의 예시·표기·적용 범위를 다시 확인했다"
PARTICLE_FIELDS = (
    "core_answer_ko",
    "definition_ko",
    "mechanism_ko",
    "purpose_ko",
    "limitations_ko",
)
ROLES = {"definition", "mechanism", "formula", "figure", "comparison", "example", "limitation"}


def particle_fields(row):
    for field in PARTICLE_FIELDS:
        yield row, field, field
    for index, _ in enumerate(row["misconceptions_ko"]):
        yield row["misconceptions_ko"], index, f"misconceptions_ko[{index}]"
    for index, contrast in enumerate(row["contrast_with"]):
        yield contrast, "difference_ko", f"contrast_with[{index}].difference_ko"
    yield row["lecture_alignment"], "lecture_summary", "lecture_alignment.lecture_summary"


def particle_lookup(rules):
    by_term = {term.casefold(): rule for term, rule in rules.items()}
    terms = "|".join(map(re.escape, sorted(by_term, key=len, reverse=True)))
    alternatives = {}
    for rule in rules.values():
        for pair in rule["particles"]:
            alternatives.update((item, pair) for item in pair.split("/"))
    particles = "|".join(sorted(alternatives, key=len, reverse=True))
    pattern = re.compile(
        rf"(?<![A-Za-z0-9_+\[\]-])(?P<term>{terms})(?P<particle>{particles})(?![가-힣])",
        flags=re.IGNORECASE,
    )
    return pattern, by_term, alternatives


def fix_particles(row, lookup, wording=None):
    pattern, terms, families = lookup
    changes = []
    wording = wording or {}
    for container, key, field in particle_fields(row):
        original = container[key]
        if not original:
            continue
        matches = []

        def replace(match, matches=matches):
            term, particle = match.group("term", "particle")
            rule = terms[term.casefold()]
            corrected = rule["particles"].get(families[particle], particle)
            if corrected != particle:
                matches.append((term, rule["reading"]))
            return term + corrected

        after = pattern.sub(replace, original)
        edit = wording.get(field)
        if edit:
            assert edit["before"] in after
            after = after.replace(edit["before"], edit["after"], 1)
            assert pattern.sub(replace, after) == after
        container[key] = after
        for term, reading in matches:
            changes.append(
                {
                    "concept_id": row["concept_id"],
                    "field": field,
                    "before": original,
                    "after": after,
                    "term": term,
                    "reading": reading,
                    **({"reason": edit["reason"]} if edit else {}),
                }
            )
    return changes


def validate_visual(visual, queue, allowed):
    expected = {identity(row) for row in queue}
    assert len(queue) == len(expected)
    assert expected <= allowed
    assert len(visual) == len(expected)
    assert {identity(row) for row in visual} == expected
    for row in visual:
        assert row["method"] == "visual_read"
        assert row["confidence"] in {"high", "medium", "low"}
        if row["formula"] is not None:
            assert row["formula"].strip() and row["formula_checked_dpi"] >= 200
        if "duplicate_of" in row:
            assert identity({"source": row["duplicate_of"]}) in expected
            assert row["duplicate_of"] != row["source"]
        for item in row["concepts"]:
            assert bool(item["concept_id"]) != bool(item["new_term"])
            assert item["role"] in ROLES
            assert item["emphasis"]


def add_concept(entry, parent, observations, digests):
    concept = {**entry["concept"], "domain": parent["domain"]}
    sources = [
        {
            "file": page["file"],
            "page": page["page"],
            "role": "example" if role == "comparison" else role,
        }
        for page, role, _, _ in observations
    ]
    concept["lecture_sources"] = sources
    concept["coverage_stats"] = stats = coverage_stats(sources, digests)
    concept["coverage_depth"] = depth(stats)
    concept["notes"] = ""
    concept["facets"] = {
        name: {
            "text_ko": None,
            "status": "missing",
            "evidence": None,
            "sources": [],
            "alternatives": [],
        }
        for name in FACETS
    }
    for name, annotation in entry["facets"].items():
        selected = [observations[i] for i in annotation["observations"]]
        methods = {method for _, _, _, method in selected}
        concept["facets"][name].update(
            text_ko=annotation["text_ko"],
            status="partial",
            evidence="both" if len(methods) == 2 else next(iter(methods)),
            sources=[{**source, "evidence": method} for source, _, _, method in selected],
        )
    missing = required_facets(concept)
    concept["enrichment_needed"] = {
        "needed": bool(missing),
        "reason": "시각 근거에서 확인할 수 없는 항목 " + ", ".join(missing) if missing else "",
    }
    return concept


def new_unit(entry, concept, writer, sources):
    row = deepcopy(entry["unit"])
    row.update(
        concept_id=concept["concept_id"],
        writer=writer,
        provenance="llm_teacher",
        review_status="unverified",
        sources={"lecture": sources, "external": []},
        terminology={
            **{
                f: concept[f]
                for f in ("canonical_term", "aliases_ko", "aliases_en", "preserve_english")
            },
            "full_form": entry.get("full_form"),
        },
    )
    mixed = set(entry["lecture_basis"])
    row["basis"] = {field: ["model_knowledge"] if row[field] else [] for field in FIELDS}
    for field in mixed:
        row["basis"][field].append("lecture")
    row["basis"]["lecture_alignment"] = ["lecture"]
    return row


def add_visual_evidence(row, observations):
    if not observations:
        return False
    citations = {identity({"source": source}): source for source in row["sources"]["lecture"]}
    summaries = []
    for source, role, observation, method in observations:
        key = identity({"source": source})
        citations.setdefault(key, source)
        if method == "visual_read":
            summaries.append({"source": source, "role": role, "observation": observation})
    row["sources"]["lecture"] = list(citations.values())
    if summaries:
        row["lecture_alignment"]["visual_evidence"] = summaries
    return bool(summaries)


def assemble(root, writer):
    private = root / "data_private"
    knowledge = private / "knowledge"
    review = knowledge / "review"
    extracted = private / "extracted"
    rules = load(review / "particle_rules.json")
    lookup = particle_lookup(rules)
    notes = load(review / "p2f_difference_edits.json")
    wording = load(review / "p2f_wording_edits.json")
    candidates = load(knowledge / "cku_v2_1_candidates.json")
    base = read_jsonl(knowledge / "cku_v2.jsonl")
    current_map = knowledge / "concept_map.json"
    backup = knowledge / "concept_map.p2f_previous.json"
    current_document = load(current_map)
    document = load(backup) if backup.is_file() else current_document
    concepts = {row["concept_id"]: row for row in document["concepts"]}
    corpus = load(private / "audit/corpus_v2.json")["pages"]
    allowed = {identity(row) for row in corpus}
    canonical = {(unicodedata.normalize("NFC", file), page): file for file, page in allowed}
    digests = {identity(row)[0]: row["sha256"] for row in corpus}
    queue = load(extracted / "visual_queue_v2.json")["pages"]
    visual = read_jsonl(extracted / "visual_terms.jsonl")
    validate_visual(visual, queue, allowed)
    by_term = {entry["concept"]["canonical_term"]: entry for entry in candidates["added"]}
    rejected = {entry["term"] for entry in candidates["rejected"]}
    observations = defaultdict(dict)
    for page in visual:
        page_source = page["source"]
        for item in page["concepts"]:
            concept_id = item["concept_id"]
            if not concept_id:
                term = item["new_term"]
                if term in rejected:
                    continue
                concept_id = by_term[term]["concept"]["concept_id"]
            key = identity(page)
            observations[concept_id][key] = (
                page_source,
                item["role"],
                item["emphasis"],
                "visual_read",
            )

    changes = []
    revised = []
    additions = []
    for unit in base:
        key = unit["concept_id"]
        row = deepcopy(unit)
        alignment = row["lecture_alignment"]
        delta = []
        if TEMPLATE in (alignment["difference_note"] or ""):
            edit = notes[key]
            alignment["difference_note"] = edit["note"]
            if edit["note"]:
                assert edit["sources"]
                alignment["difference_sources"] = [
                    {
                        "file": canonical[(unicodedata.normalize("NFC", s["file"]), s["page"])],
                        "page": s["page"],
                    }
                    for s in edit["sources"]
                ]
            delta.append("difference_note")
        if add_visual_evidence(row, observations[key].values()):
            delta.append("visual_evidence")
        fixes = fix_particles(row, lookup, wording.get(key))
        if fixes:
            delta.insert(0, "particles")
            changes.extend(fixes)
        row.update(version="2.1", revision={"based_on": "cku_v2", "changes": delta})
        revised.append(row)

    for entry in candidates["added"]:
        key = entry["concept"]["concept_id"]
        parent = concepts[entry["concept"]["parent_id"]]
        evidence = list(observations[key].values())
        for item in entry.get("text_evidence", []):
            source = item["source"]
            assert identity({"source": source}) in allowed
            evidence.append((source, item["role"], item["observation"], "text_layer"))
        assert evidence and key not in concepts
        concept = add_concept(entry, parent, evidence, digests)
        units_sources = [source for source, _, _, _ in evidence]
        row = new_unit(entry, concept, writer, units_sources)
        visual_added = add_visual_evidence(row, evidence)
        fixes = fix_particles(row, lookup)
        changes.extend(fixes)
        revision = ["visual_evidence", "new_concept"] if visual_added else ["new_concept"]
        if fixes:
            revision.insert(0, "particles")
        row.update(version="2.1", revision={"based_on": "cku_v2", "changes": revision})
        revised.append(row)
        concepts[key] = concept
        additions.append(
            {"concept_id": key, "term": concept["canonical_term"], "sources": units_sources}
        )

    validate(revised, concepts, allowed)
    assert set(observations) <= concepts.keys()
    assert all(not fix_particles(row, lookup) for row in revised)
    result_map = {**document, "concepts": list(concepts.values())}
    if current_document != result_map:
        receipt = knowledge / "cku_v2_1_new_concepts.json"
        prior = load(receipt) if backup.is_file() and receipt.is_file() else {}
        previous_ids = {row["concept_id"] for row in prior.get("added", [])}
        preserved = [
            row for row in current_document["concepts"] if row["concept_id"] not in previous_ids
        ]
        if preserved != document["concepts"]:
            raise ValueError("Existing concept-map entries changed after the P2f backup")
        if not backup.is_file():
            with backup.open("xb") as destination:
                destination.write(current_map.read_bytes())
        temp = current_map.with_suffix(".tmp")
        write_json(temp, result_map)
        temp.replace(current_map)
    write_jsonl(knowledge / "cku_v2_1.jsonl", revised)
    write_jsonl(review / "particle_fixes.jsonl", changes)
    write_json(
        knowledge / "cku_v2_1_new_concepts.json",
        {
            "added": additions,
            "rejected": candidates["rejected"],
        },
    )
    progress = load(knowledge / "cku_progress.json")
    progress.update(
        total=len(revised), completed=len(revised), pending=[], last=revised[-1]["concept_id"]
    )
    progress["visual"].update(
        total=len(queue),
        completed=len(visual),
        pending=[],
        last=visual[-1]["source"],
        status="completed",
        unreadable=[
            {"source": row["source"], "reason": row["unreadable"]}
            for row in visual
            if row.get("unreadable")
        ],
    )
    write_json(knowledge / "cku_progress.json", progress)
    return {
        "units": len(revised),
        "particles": dict(Counter(change["field"] for change in changes)),
        "difference_notes": sum("difference_note" in row["revision"]["changes"] for row in revised),
        "visual_pages": len(visual),
        "visual_confidence": dict(Counter(row["confidence"] for row in visual)),
        "new_concepts": len(additions),
        "strengthened": sum(
            "visual_evidence" in row["revision"]["changes"]
            and "new_concept" not in row["revision"]["changes"]
            for row in revised
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--model", required=True)
    parser.add_argument("--reasoning", required=True)
    parser.add_argument("--date", required=True)
    args = parser.parse_args()
    print(
        assemble(
            args.root.resolve(),
            {
                "tool": "codex",
                "model": args.model,
                "reasoning": args.reasoning,
                "date": args.date,
            },
        )
    )


if __name__ == "__main__":
    main()
