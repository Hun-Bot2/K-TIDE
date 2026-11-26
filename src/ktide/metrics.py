"""Rule-based answer metrics computed in Python (no LLM involved).

Definitions (documented so the paper can cite them precisely):

* word_count   — ``len(answer.split())``: whitespace-separated tokens (어절), as stated in the
                 professor's system prompt ("공백으로 구분한 30어절").
* sentence_count — number of non-empty segments after splitting on sentence-final punctuation
                 ``. ! ? 。`` (and their full-width forms) that are followed by whitespace or
                 end-of-string. A period between digits (``0.5``) or inside a token without a
                 following space (``e.g.x``) does not split. Trailing text without final
                 punctuation counts as one sentence. Newline-separated lines also split.
* max_tokens_reached — the answer re-tokenized has >= MAX_NEW_TOKENS tokens, i.e. generation was
                 likely cut off by the token budget rather than by EOS (heuristic, re-tokenization).
* hangul_ratio — Hangul syllables / all letters (Hangul + Latin + Han). Measures language mix.
* has_han      — answer contains CJK ideographs (Chinese characters): a language-confusion signal.
* is_polite    — the answer ends in a polite/formal register ending (~니다, ~요, ~세요, ~죠).
                 Training answers use the plain register (~이다), so this tracks style transfer.
* mentions_source — the answer refers to its source material (강의, 슬라이드, 수업, 교재),
                 a habit a model can pick up from training answers that mention the lecture.
"""

from __future__ import annotations

import re
from statistics import mean

WORD_LIMIT = 30
SENTENCE_LIMIT = 2

_SENT_END = re.compile(r"(?<=[.!?。．！？])(?=\s|$)")
_HANGUL = re.compile(r"[가-힣]")
_LATIN = re.compile(r"[A-Za-z]")
_HAN = re.compile(r"[一-鿿]")
_POLITE_END = re.compile(r"(니다|세요|어요|아요|해요|에요|예요|죠|요)[.!?。]?\s*$")
_SOURCE = re.compile(r"강의|슬라이드|수업|교재")


def style_stats(answer: str) -> dict:
    return {
        "is_polite": bool(_POLITE_END.search(answer.strip())),
        "mentions_source": bool(_SOURCE.search(answer)),
    }


def word_count(answer: str) -> int:
    return len(answer.split())


def sentence_count(answer: str) -> int:
    text = answer.strip()
    if not text:
        return 0
    count = 0
    for line in text.splitlines():
        for seg in _SENT_END.split(line):
            if seg.strip():
                count += 1
    return count


def script_stats(answer: str) -> dict:
    h = len(_HANGUL.findall(answer))
    lat = len(_LATIN.findall(answer))
    han = len(_HAN.findall(answer))
    total = h + lat + han
    return {
        "hangul_ratio": round(h / total, 4) if total else None,
        "has_han": han > 0,
    }


def answer_metrics(answer: str, n_tokens: int | None, max_new_tokens: int) -> dict:
    wc = word_count(answer)
    sc = sentence_count(answer)
    return {
        "word_count": wc,
        "sentence_count": sc,
        "within_word_limit": wc <= WORD_LIMIT,
        "within_sentence_limit": 1 <= sc <= SENTENCE_LIMIT,
        "is_empty": not answer.strip(),
        "n_tokens": n_tokens,
        "max_tokens_reached": (n_tokens is not None and n_tokens >= max_new_tokens),
        **script_stats(answer),
        **style_stats(answer),
    }


def _rate(rows: list[dict], key: str) -> float | None:
    return round(mean(1.0 if r[key] else 0.0 for r in rows), 4) if rows else None


def aggregate_rule_metrics(rows: list[dict]) -> dict:
    if not rows:
        return {"n": 0}
    return {
        "n": len(rows),
        "word_limit_compliance": _rate(rows, "within_word_limit"),
        "sentence_limit_compliance": _rate(rows, "within_sentence_limit"),
        "both_limits_compliance": round(
            mean(float(r["within_word_limit"] and r["within_sentence_limit"]) for r in rows), 4
        ),
        "empty_rate": _rate(rows, "is_empty"),
        "max_tokens_reached_rate": _rate(rows, "max_tokens_reached"),
        "han_rate": _rate(rows, "has_han"),
        "polite_rate": _rate(rows, "is_polite"),
        "source_mention_rate": _rate(rows, "mentions_source"),
        "mean_word_count": round(mean(r["word_count"] for r in rows), 2),
        "max_word_count": max(r["word_count"] for r in rows),
    }
