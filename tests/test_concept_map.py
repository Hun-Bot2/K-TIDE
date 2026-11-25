"""Validate the private P2c artifacts when the local lecture corpus is available."""

import json
from collections import Counter
from pathlib import Path

import pytest

from ktide.knowledge.build import DOMAINS, FACETS
from ktide.knowledge.coverage import coverage_stats, depth, required_facets
from ktide.professor import REPO_ROOT

PRIVATE = REPO_ROOT / "data_private"
MAP = PRIVATE / "knowledge/concept_map.json"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.skipif(not MAP.is_file(), reason="Private concept map is unavailable")
def test_private_concept_map():
    inventory = read(PRIVATE / "audit/inventory.json")["files"]
    counts = {row["source"]["file"]: row["page_count"] for row in inventory}
    digests = {row["source"]["file"]: row["sha256"] for row in inventory}
    extracted = PRIVATE / "extracted"
    with (extracted / "visual_transcripts.jsonl").open(encoding="utf-8") as stream:
        transcripts = [json.loads(line) for line in stream]
    seen = {(row["source"]["file"], row["source"]["page"]) for row in transcripts}
    assert len(seen) == len(transcripts)
    queue = read(extracted / "visual_queue.json")["pages"]
    selected = {(row["source"]["file"], row["source"]["page"]) for row in queue}
    assert seen <= selected
    allowed = {
        (row["source"]["file"], row["source"]["page"])
        for row in read(PRIVATE / "audit/p2_corpus_draft.json")["pages"]
    }

    def check_source(source):
        file, page = source["file"], source["page"]
        pdf = (REPO_ROOT / file).resolve()
        assert pdf.is_relative_to((REPO_ROOT / "NLP").resolve())
        assert pdf.suffix.lower() == ".pdf" and pdf.is_file()
        assert type(page) is int and 1 <= page <= counts[file]
        assert (file, page) in allowed

    document = read(MAP)
    assert document["schema_version"] == 2
    assert read(MAP.with_name("concept_map.p2b.json"))["schema_version"] == 1
    for row in transcripts:
        check_source(row["source"])
        assert row["sha256"] == digests[row["source"]["file"]]
        assert row["method"] == "visual_read" and row["model"]
        assert row["confidence"] in {"high", "medium", "low"}
    assert {"tool", "model", "reasoning"} <= document["created_by"].keys()
    concepts = document["concepts"]
    ids = Counter(item["concept_id"] for item in concepts)
    assert ids and all(count == 1 for count in ids.values())
    for item in concepts:
        assert {
            "concept_id",
            "canonical_term",
            "ko_name",
            "aliases_ko",
            "aliases_en",
            "abbreviations",
            "preserve_english",
            "domain",
            "parent_id",
            "related_ids",
            "coverage_depth",
            "facets",
            "lecture_sources",
            "enrichment_needed",
            "notes",
        } <= item.keys()
        assert item["domain"] in {*DOMAINS.values(), "other"}
        assert item["domain"] != "other" or item["notes"]
        assert item["parent_id"] is None or item["parent_id"] in ids
        assert set(item["related_ids"]) <= ids.keys()
        assert item["coverage_stats"] == coverage_stats(item["lecture_sources"], digests)
        assert item["coverage_depth"] == depth(item["coverage_stats"])
        if required_facets(item):
            assert item["enrichment_needed"]["needed"] is True
            assert item["enrichment_needed"]["reason"]
        assert set(item["facets"]) == set(FACETS)
        assert item["lecture_sources"]
        for source in item["lecture_sources"]:
            assert source["role"] in {
                "definition",
                "mechanism",
                "example",
                "formula",
                "figure",
                "mention",
            }
            check_source(source)
        for facet in item["facets"].values():
            status = facet["status"]
            assert status in {"stated", "partial", "figure_only", "missing"}
            if status in {"stated", "partial"}:
                assert facet["text_ko"] and facet["sources"]
            else:
                assert facet["text_ko"] is None
                assert bool(facet["sources"]) == (status == "figure_only")
            sources = list(facet["sources"])
            for alternative in facet["alternatives"]:
                assert alternative["text_ko"] and alternative["sources"]
                sources.extend(alternative["sources"])
            methods = set()
            for source in sources:
                check_source(source)
                method = source["evidence"]
                assert method in {"text_layer", "visual_read"}
                if method == "visual_read":
                    assert (source["file"], source["page"]) in seen
                methods.add(method)
            expected = "both" if len(methods) == 2 else next(iter(methods), None)
            assert facet["evidence"] == expected

    checks = read(MAP.with_name("concept_map_checks.json"))
    assert checks["visual_read_summary"]["selected_pages"] == len(queue)
    assert checks["visual_read_summary"]["read_pages"] == len(transcripts)
    sample = read(MAP.with_name("review_sample_p2c.json"))
    assert isinstance(sample["seed"], int)
    assert len({(row["concept_id"], row["facet"]) for row in sample["facets"]}) == 20
    by_id = {item["concept_id"]: item for item in concepts}
    for row in sample["facets"]:
        facet = by_id[row["concept_id"]]["facets"][row["facet"]]
        assert facet["status"] in {"stated", "partial"}
        assert row["text_ko"] == facet["text_ko"]
        assert row["sources"] == facet["sources"]
    questions = checks["public_question_coverage"]
    assert set(questions) == set(map(str, range(1, 12)))
    for mapping in questions.values():
        assert mapping == "not_in_lecture" or (mapping and set(mapping) <= ids.keys())
    terms = read(PRIVATE / "audit/concepts.json")
    assert set(checks["terms_mapping"]) == {term["concept"] for term in terms}
    for result in checks["terms_mapping"].values():
        assert result.get("concept_id") in ids or result.get("reason")
    assert all(Path(item["file"]).suffix == ".pdf" for item in checks["files_processed"])
