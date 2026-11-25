import pytest

from ktide.judge import extract_json_array, parse_results, summarize

PREDS = [
    {"question_number": 1, "question_id": "X001"},
    {"question_number": 2, "question_id": "X002"},
]


def item(n, a, r, c, avg=None):
    return {"question_number": n, "scores": {"accuracy": a, "relevance": r, "constraints": c},
            "total_average": avg, "feedback": "f"}


def test_extract_from_fenced_text():
    assert extract_json_array('설명\n```json\n[{"a": 1}]\n```') == [{"a": 1}]


def test_parse_recomputes_average_and_keeps_reported():
    res = parse_results([item(2, 3, 5, 5, 9.9), item(1, 5, 5, 5, 5.0)], PREDS)
    assert [r.question_id for r in res] == ["X001", "X002"]
    assert res[1].total_average == pytest.approx(4.3333, abs=1e-4)
    assert res[1].judge_reported_average == 9.9
    assert summarize(res)["mean_accuracy"] == 4.0


def test_parse_rejects_missing_or_duplicate():
    with pytest.raises(ValueError):
        parse_results([item(1, 5, 5, 5)], PREDS)
    with pytest.raises(ValueError):
        parse_results([item(1, 5, 5, 5), item(1, 5, 5, 5)], PREDS)


def test_scores_out_of_range_rejected():
    with pytest.raises(ValueError):
        parse_results([item(1, 6, 5, 5), item(2, 5, 5, 5)], PREDS)
