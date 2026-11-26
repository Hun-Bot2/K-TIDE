"""Check Teacher units against the filtered private lecture corpus."""

import pytest

from ktide.audit.filter_corpus import identity
from ktide.knowledge.cku import read_jsonl, validate
from ktide.knowledge.polish_cku import TEMPLATE, fix_particles, particle_lookup, validate_visual
from ktide.knowledge.slp import chapter_files, page_count, validate_grounding
from ktide.knowledge.visual import load
from ktide.metrics import sentence_count, word_count
from ktide.professor import REPO_ROOT

PRIVATE = REPO_ROOT / "data_private"
UNIT_PATH = PRIVATE / "knowledge/cku_v1.jsonl"
PRE_POLISH_MAP = PRIVATE / "knowledge/concept_map.p2f_previous.json"


def original_concepts():
    path = PRE_POLISH_MAP if PRE_POLISH_MAP.is_file() else PRIVATE / "knowledge/concept_map.json"
    return {row["concept_id"]: row for row in load(path)["concepts"]}


@pytest.mark.skipif(not UNIT_PATH.exists(), reason="Private Teacher units unavailable")
def test_private_cku():
    allowed = {identity(row) for row in load(PRIVATE / "audit/corpus_v2.json")["pages"]}
    validate(read_jsonl(UNIT_PATH), original_concepts(), allowed)


@pytest.mark.skipif(
    not (PRIVATE / "knowledge/cku_v2.jsonl").exists(), reason="Private CKU v2 unavailable"
)
def test_private_cku_v2():
    from ktide.knowledge.revise_cku import review_items

    directory = PRIVATE / "knowledge"
    units = read_jsonl(directory / "cku_v2.jsonl")
    v1 = {r["concept_id"]: r for r in read_jsonl(directory / "cku_v1.jsonl")}
    concepts = original_concepts()
    allowed = {identity(row) for row in load(PRIVATE / "audit/corpus_v2.json")["pages"]}
    validate(units, concepts, allowed)
    assert len(units) == len(v1) == 191
    by_id = {r["concept_id"]: r for r in units}
    reviews = {r["concept_id"]: r for r in read_jsonl(directory / "review/cku_review_all.jsonl")}
    records = read_jsonl(directory / "review/cku_v2_decisions.jsonl")
    decisions = {r["concept_id"]: r for r in records}
    assert len(records) == len(decisions) == len(reviews) == 191
    assert by_id.keys() == decisions.keys() == reviews.keys() == v1.keys()
    for key, row in by_id.items():
        assert row["version"] == 2
        assert row["provenance"] == "llm_teacher"
        assert row["writer"]["model"] == "gpt-6.2-sol"
        assert row["writer"]["reasoning"] == "high"
        assert row["revision"]["based_on"] == "cku_v1"
        assert row["revision"]["review"] == "cku_review_all"
        alignment = row["lecture_alignment"]
        assert alignment["lecture_summary"].strip()
        assert alignment["status"] != "scope_unverified"
        assert row["sources"]["lecture"]
        if concepts[key]["coverage_depth"] == "core":
            assert row["misconceptions_ko"] or row.get("unfilled_reason", {}).get(
                "misconceptions_ko"
            )
        if row["terminology"]["preserve_english"]:
            assert (
                row["terminology"]["canonical_term"].casefold() in row["core_answer_ko"].casefold()
            )
        for pair in row["contrast_with"]:
            reverse = by_id[pair["concept_id"]]["contrast_with"]
            assert any(p["concept_id"] == key for p in reverse)
        expected = {
            category + ":" + identifier for category, identifier, _ in review_items(reviews[key])
        }
        actual = [d["review_item"] for d in decisions[key]["decisions"]]
        assert len(actual) == len(set(actual))
        assert set(actual) == (expected or {"verdict"})
        for decision in decisions[key]["decisions"]:
            assert decision["decision"] in {"accept", "partial", "reject"}
            assert decision["reason"]
        changed = [f for f in v1[key] if row[f] != v1[key][f]]
        assert row["revision"]["changed_fields"] == changed
        assert decisions[key]["changed_fields"] == changed


@pytest.mark.skipif(
    not (PRIVATE / "knowledge/cku_v2_1.jsonl").is_file(), reason="Private CKU v2.1 unavailable"
)
def test_private_cku_v2_1():
    knowledge = PRIVATE / "knowledge"
    extracted = PRIVATE / "extracted"
    allowed = {identity(row) for row in load(PRIVATE / "audit/corpus_v2.json")["pages"]}
    concepts = {row["concept_id"]: row for row in load(knowledge / "concept_map.json")["concepts"]}
    original = original_concepts()
    for key, value in original.items():
        assert value == concepts[key]
    units = read_jsonl(knowledge / "cku_v2_1.jsonl")
    validate(units, concepts, allowed)
    lookup = particle_lookup(load(knowledge / "review/particle_rules.json"))
    visual = read_jsonl(extracted / "visual_terms.jsonl")
    queue = load(extracted / "visual_queue_v2.json")["pages"]
    validate_visual(visual, queue, allowed)
    assert len(visual) == 270
    assert load(knowledge / "cku_progress.json")["visual"]["pending"] == []
    figures = {
        row["figure_id"]: row["representative"] for row in load(extracted / "figure_index.json")
    }
    for row, page in zip(visual, queue, strict=True):
        assert row["source"] == page["source"]
        expected = {
            region["figure_id"] for region in page.get("skip_regions", []) if "figure_id" in region
        }
        refs = row.get("figure_refs", [])
        assert {ref["figure_id"] for ref in refs} == expected
        assert all(ref["representative"] == figures[ref["figure_id"]] for ref in refs)
    verified_pages = {identity(row) for row in visual}
    for row in units:
        assert row["version"] == "2.1"
        assert row["revision"]["based_on"] == "cku_v2"
        assert not fix_particles(row, lookup)
        assert 1 <= word_count(row["core_answer_ko"]) <= 30
        assert 1 <= sentence_count(row["core_answer_ko"]) <= 2
        alignment = row["lecture_alignment"]
        assert TEMPLATE not in (alignment["difference_note"] or "")
        assert all(
            identity({"source": s}) in allowed for s in alignment.get("difference_sources", [])
        )
        assert all(identity(s) in verified_pages for s in alignment.get("visual_evidence", []))
        if row["concept_id"] not in original:
            assert row["review_status"] == "unverified"
            assert "new_concept" in row["revision"]["changes"]


@pytest.mark.skipif(
    not (PRIVATE / "knowledge/cku_v3.jsonl").is_file(), reason="Private CKU v3 unavailable"
)
def test_private_cku_v3():
    knowledge = PRIVATE / "knowledge"
    textbook = PRIVATE / "external/slp"
    units = read_jsonl(knowledge / "cku_v3.jsonl")
    concepts = {row["concept_id"]: row for row in load(knowledge / "concept_map.json")["concepts"]}
    allowed = {identity(row) for row in load(PRIVATE / "audit/corpus_v2.json")["pages"]}
    lookup = particle_lookup(load(knowledge / "review/particle_rules.json"))
    pages = read_jsonl(textbook / "pages.jsonl")
    decisions = read_jsonl(textbook / "concept_evidence.jsonl")
    actual_pages = {
        (chapter, page)
        for chapter, path in chapter_files(REPO_ROOT)
        for page in range(1, page_count(path) + 1)
    }
    assert {(row["chapter"], row["page"]) for row in pages} == actual_pages
    validate_grounding(units, concepts, allowed, pages, decisions, lookup)
    previous = {row["concept_id"]: row for row in read_jsonl(knowledge / "cku_v2_1.jsonl")}
    receipts = read_jsonl(knowledge / "review/cku_v3_changes.jsonl")
    audit = {row["concept_id"]: row for row in receipts}
    assert len(audit) == len(receipts) == len(units)
    assert audit.keys() == previous.keys() == concepts.keys()
    for row in units:
        key = row["concept_id"]
        old = previous[key]
        assert row["sources"]["lecture"] == old["sources"]["lecture"]
        assert row["sources"]["external"] == old["sources"]["external"]
        assert row["provenance"] == old["provenance"] == "llm_teacher"
        assert 1 <= word_count(row["core_answer_ko"]) <= 30
        assert 1 <= sentence_count(row["core_answer_ko"]) <= 2
        changed = [f for f in old if f not in {"version", "revision"} and old[f] != row[f]]
        assert row["revision"]["changed_fields"] == changed
        assert [edit["field"] for edit in audit[key]["changes"]] == changed
        for edit in audit[key]["changes"]:
            assert edit["before"] == old[edit["field"]]
            assert edit["after"] == row[edit["field"]]
            assert edit["reason"]
            assert all(ref in row["sources"]["slp"] for ref in edit["sources"])
