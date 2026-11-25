"""Check Teacher units against the filtered private lecture corpus."""

import pytest

from ktide.audit.filter_corpus import identity
from ktide.knowledge.cku import read_jsonl, validate
from ktide.knowledge.visual import load
from ktide.professor import REPO_ROOT

PRIVATE = REPO_ROOT / "data_private"
UNIT_PATH = PRIVATE / "knowledge/cku_v1.jsonl"


@pytest.mark.skipif(not UNIT_PATH.exists(), reason="Private Teacher units unavailable")
def test_private_cku():
    concepts = load(PRIVATE / "knowledge/concept_map.json")["concepts"]
    allowed = {identity(row) for row in load(PRIVATE / "audit/corpus_v2.json")["pages"]}
    validate(read_jsonl(UNIT_PATH), {c["concept_id"]: c for c in concepts}, allowed)


@pytest.mark.skipif(
    not (PRIVATE / "knowledge/cku_v2.jsonl").exists(), reason="Private CKU v2 unavailable"
)
def test_private_cku_v2():
    from ktide.knowledge.revise_cku import review_items

    directory = PRIVATE / "knowledge"
    units = read_jsonl(directory / "cku_v2.jsonl")
    v1 = {r["concept_id"]: r for r in read_jsonl(directory / "cku_v1.jsonl")}
    concepts = {r["concept_id"]: r for r in load(directory / "concept_map.json")["concepts"]}
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
