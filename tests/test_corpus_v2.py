"""Check the filtered lecture corpus when its private artifacts are present."""

import json

import pytest

from ktide.audit.filter_corpus import identity
from ktide.professor import REPO_ROOT

PRIVATE = REPO_ROOT / "data_private"
AUDIT = PRIVATE / "audit"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.skipif(not (AUDIT / "corpus_v2.json").exists(), reason="Private corpus unavailable")
def test_corpus_filter_contract():
    with (AUDIT / "page_filter.jsonl").open(encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream]
    by_page = {identity(row): row for row in rows}
    inventory = load(AUDIT / "inventory.json")
    expected = {
        identity(page): file["sha256"] for file in inventory["files"] for page in file["pages"]
    }
    assert len(rows) == len(by_page) == len(expected)
    assert {key: row["sha256"] for key, row in by_page.items()} == expected

    for row in rows:
        duplicate = row.get("duplicate_of") or row.get("build_step_of")
        if duplicate:
            assert row["decision"] == "exclude"
            target = by_page[identity({"source": duplicate})]
            assert target["decision"] == "keep"
            assert not target.get("duplicate_of") and not target.get("build_step_of")

    for label in load(AUDIT / "page_labels.json")["labels"]:
        row = by_page[identity(label)]
        assert row["sha256"] == label["sha256"]
        assert row["decision"] == label["label"]
        assert row["needs_human_review"] is False

    corpus = load(AUDIT / "corpus_v2.json")["pages"]
    kept = {identity(row): row["sha256"] for row in rows if row["decision"] == "keep"}
    assert len(corpus) == len(kept)
    assert {identity(row): row["sha256"] for row in corpus} == kept

    extracted = PRIVATE / "extracted"
    queue = load(extracted / "visual_queue_v2.json")["pages"]
    visual = {identity(row): row for row in queue}
    assert len(visual) == len(queue)
    assert all(kept[key] == row["sha256"] for key, row in visual.items())
    for figure in load(extracted / "figure_index.json"):
        representative = identity({"source": figure["representative"]})
        assert representative in kept
        for occurrence in figure["occurrences"]:
            key = identity({"source": occurrence})
            assert key in kept
            if key != representative and key in visual:
                assert {
                    "bbox": occurrence["bbox"],
                    "reason": "repeated_figure",
                    "figure_id": figure["figure_id"],
                } in visual[key]["skip_regions"]
