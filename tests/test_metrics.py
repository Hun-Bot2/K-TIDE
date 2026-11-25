from ktide.metrics import aggregate_rule_metrics, answer_metrics, sentence_count, word_count


def test_word_count_whitespace():
    assert word_count("토큰화는 텍스트를 토큰으로  나눈다.") == 4
    assert word_count("") == 0


def test_sentence_count_basic():
    assert sentence_count("첫 문장이다. 두 번째 문장이다.") == 2
    assert sentence_count("마침표 없는 문장") == 1
    assert sentence_count("") == 0


def test_sentence_count_decimal_not_split():
    assert sentence_count("학습률은 0.5이다.") == 1


def test_sentence_count_newlines_split():
    assert sentence_count("한 줄\n두 줄") == 2


def test_answer_metrics_limits():
    m = answer_metrics(" ".join(["단어"] * 31) + ".", n_tokens=40, max_new_tokens=128)
    assert m["word_count"] == 31 and not m["within_word_limit"]
    assert m["within_sentence_limit"] and not m["max_tokens_reached"]


def test_han_detection_and_aggregate():
    rows = [answer_metrics("中文 답변.", 5, 128), answer_metrics("한국어 답변.", 128, 128)]
    assert rows[0]["has_han"] and not rows[1]["has_han"]
    agg = aggregate_rule_metrics(rows)
    assert agg["han_rate"] == 0.5 and agg["max_tokens_reached_rate"] == 0.5
