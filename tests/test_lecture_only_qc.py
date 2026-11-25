import unicodedata
from pathlib import Path

import pytest

from ktide.train_data.lecture_only_qc import FORBIDDEN_PDF, PROMPT, check_dataset, validate

SYNTHETIC_PAGE = ("NLP/synthetic-fixture.pdf", 1, "text_layer")


@pytest.fixture
def pair():
    return {
        "qa_id": "m1-00001",
        "concept_id": "synthetic",
        "domain": "synthetic_domain",
        "question_type": "definition",
        "question_form": "en",
        "question_ko": "VectorC는 무엇을 뜻하나요?",
        "answer_translated_ko": "방향 표현은 순서를 나타낸다.",
        "answer_preserved_ko": "VectorC는 순서를 나타낸다.",
        "evidence": [{"file": SYNTHETIC_PAGE[0], "page": 1, "source": "text_layer"}],
        "basis": "lecture",
        "generator": {"tool": "codex", "model": "synthetic", "reasoning": "test", "prompt": PROMPT},
    }


def run_check(*pairs):
    return validate(
        list(pairs),
        concepts={
            "synthetic": {
                "canonical_term": "VectorC",
                "domain": "synthetic_domain",
                "preserve_english": True,
            }
        },
        unseen={"withheld_fixture"},
        evidence={SYNTHETIC_PAGE},
        translations={"VectorC": "방향 표현", "VectorD": "길이 표현"},
        particle_rules={"VectorC": {"particles": {"은/는": "는"}}},
    )


def test_format_and_matched_pair(pair):
    report = run_check(pair)
    assert report["failure_count"] == 0
    assert report["exact_pair_after_translation_count"] == 1
    assert report["min_normalized_pair_similarity"] == 1
    del pair["answer_translated_ko"]
    assert run_check(pair)["failures"] == [{"code": "invalid_required_fields", "row": 1}]


def test_forbidden_page_and_unseen_concept(pair):
    pair["concept_id"] = "withheld_fixture"
    pair["evidence"][0].update(file="NLP/" + unicodedata.normalize("NFD", FORBIDDEN_PDF), page=11)
    assert {"forbidden_page", "unseen_concept"} <= {
        failure["code"] for failure in run_check(pair)["failures"]
    }


def test_language_pair_particle_and_length_failures(pair):
    pair["answer_preserved_ko"] = "VectorC은 " + "말 " * 32 + "끝."
    pair["answer_translated_ko"] = "길이 표현은 첫째다. 둘째다. 셋째다."
    assert {"answer_pair_similarity", "particle_rule", "answer_term_mismatch"} <= {
        failure["code"] for failure in run_check(pair)["failures"]
    }
    assert {
        failure["field"]
        for failure in run_check(pair)["failures"]
        if failure["code"] == "answer_length"
    } == {"answer_translated_ko", "answer_preserved_ko"}


def test_exact_and_near_duplicate_questions(pair):
    pair["question_ko"] = (
        "VectorC의 여러 방향을 한꺼번에 표현할 때 무엇을 나타낼 수 있는지 설명해 주세요."
    )
    exact = {**pair, "qa_id": "m1-00002", "question_ko": pair["question_ko"].replace(" ", "")}
    near = {**pair, "qa_id": "m1-00003", "question_ko": pair["question_ko"].replace("여러", "모든")}
    codes = {failure["code"] for failure in run_check(pair, exact, near)["failures"]}
    assert codes == {"duplicate_question", "near_duplicate_question"}


def test_local_lecture_only_dataset():
    private_root = Path(__file__).resolve().parents[1] / "data_private"
    dataset = private_root / "train/m1_lecture_only"
    if not (dataset / "qa.jsonl").is_file():
        pytest.skip("local lecture-only data is private")
    report = check_dataset(private_root, dataset)
    assert report["qa_count"] > 0
    assert report["failure_count"] == 0, report["failures"]
