"""Validate paired lecture-only M1 and M2 answers and write an aggregate QC report."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path
from statistics import mean

from ktide.metrics import SENTENCE_LIMIT, WORD_LIMIT, sentence_count, word_count

PROMPT = "prompts/codex_m1_lecture_only_qa.md"
FORBIDDEN_PDF = "2026-NLP-LLM 모델 경량화.pdf"
FORBIDDEN_PAGES = {9, 11, 12}
QUESTION_TYPES = {
    "definition",
    "purpose",
    "mechanism",
    "comparison",
    "limitation",
    "result",
    "judgment",
    "calculation",
}
QUESTION_FORMS = {"ko", "en", "abbr", "mixed"}
ANSWER_FIELDS = ("answer_translated_ko", "answer_preserved_ko")
TEXT_FIELDS = (
    "qa_id",
    "concept_id",
    "domain",
    "question_type",
    "question_form",
    "question_ko",
    *ANSWER_FIELDS,
)
REQUIRED_FIELDS = {*TEXT_FIELDS, "evidence", "basis", "generator"}
PARTICLE_PAIRS = ("으로/로", "은/는", "이/가", "을/를", "과/와")
PARTICLE_SLOTS = {form: pair for pair in PARTICLE_PAIRS for form in pair.split("/")}
PARTICLE = r"(?:" + "|".join(PARTICLE_SLOTS) + r")(?![가-힣])"
LATIN = re.compile(r"[A-Za-z]")
HANGUL = re.compile(r"[가-힣]")
MIN_PAIR_SIMILARITY = 0.85
DUPLICATE_SIMILARITY = 0.8
MAX_PER_CONCEPT = 8


def read_json(path: Path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def read_jsonl(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def page_key(source: dict) -> tuple[str, int]:
    return unicodedata.normalize("NFC", source["file"]), source["page"]


def forbidden_page(key: tuple[str, int]) -> bool:
    file, page = key
    return Path(file).name == FORBIDDEN_PDF and page in FORBIDDEN_PAGES


def lecture_evidence(private_root: Path) -> set[tuple[str, int, str]]:
    corpus = read_json(private_root / "audit/corpus_v2.json")["pages"]
    hashes = {page_key(row["source"]): row["sha256"] for row in corpus}
    evidence = {
        (*key, "text_layer")
        for row in read_json(private_root / "knowledge/lecture_pages.json")
        if (key := page_key(row["source"])) in hashes
        and not forbidden_page(key)
        and hashes[key] == row["sha256"]
        and row["text"].strip()
    }
    for filename in ("visual_terms.jsonl", "visual_transcripts.jsonl"):
        for row in read_jsonl(private_root / "extracted" / filename):
            key = page_key(row["source"])
            if (
                key in hashes
                and not forbidden_page(key)
                and row["method"] == "visual_read"
                and row.get("confidence") != "low"
                and row.get("sha256", hashes[key]) == hashes[key]
            ):
                evidence.add((*key, "visual_read"))
    return evidence


def korean_particle(term: str, pair: str) -> str:
    first, second = pair.split("/")
    final = (ord(term.rstrip(")]")[-1]) - ord("가")) % 28
    return first if final and (pair != "으로/로" or final != 8) else second


def english_particle(term: str, pair: str, rules: dict) -> str | None:
    tail = re.split(r"[\s/–—-]+", term)[-1].casefold()
    rule = rules.get(term.casefold()) or rules.get(tail)
    return rule["particles"].get(pair) if rule else None


def _terms_pattern(terms, *, latin_boundaries: bool) -> str:
    alternatives = "|".join(map(re.escape, sorted(terms, key=lambda term: (-len(term), term))))
    if latin_boundaries:
        return rf"(?<![A-Za-z0-9])(?:{alternatives})(?![A-Za-z0-9])"
    return rf"(?<![가-힣])(?:{alternatives})(?={PARTICLE}|[^가-힣]|$)"


def normalized_question(question: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFKC", question).casefold() if char.isalnum()
    )


def trigrams(value: str) -> set[str]:
    return {value[index : index + 3] for index in range(max(1, len(value) - 2))}


def _primary_term_present(concept: dict, terms: set[str]) -> bool:
    canonical = concept["canonical_term"]
    if "/" in canonical and all(part.casefold() in terms for part in canonical.split("/")):
        return True
    accepted = (canonical, *concept.get("aliases_en", []), *concept.get("abbreviations", []))
    return any(term.strip().casefold() in terms for term in accepted)


def _valid_generator(value) -> bool:
    return (
        isinstance(value, dict)
        and value.get("tool") == "codex"
        and value.get("prompt") == PROMPT
        and all(
            isinstance(value.get(key), str) and value[key].strip() for key in ("model", "reasoning")
        )
    )


def validate(
    rows: list[dict],
    *,
    concepts: dict,
    unseen: set[str],
    evidence: set[tuple[str, int, str]],
    translations: dict[str, str],
    particle_rules: dict,
) -> dict:
    if not translations or not all(
        LATIN.search(term) and HANGUL.search(ko) and not LATIN.search(ko)
        for term, ko in translations.items()
    ):
        raise ValueError("term_translations.json must map English terms to Korean spellings")

    term_pattern = _terms_pattern(translations, latin_boundaries=True)
    english = re.compile(rf"(?P<term>{term_pattern})(?P<particle>{PARTICLE})?")
    markers = {term: chr(0xE000 + i) for i, term in enumerate(sorted(set(translations.values())))}
    korean = re.compile(_terms_pattern(markers, latin_boundaries=False))
    rules = {term.casefold(): rule for term, rule in particle_rules.items()}
    failures = []
    by_concept, by_type, by_form, by_domain = (Counter() for _ in range(4))
    word_counts = {field: [] for field in ANSWER_FIELDS}
    question_index = []
    seen_ids = set()
    similarities = []
    exact_pairs = 0

    def fail(code: str, **details) -> None:
        failures.append({"code": code, **details})

    if not rows:
        fail("empty_dataset")
    for index, row in enumerate(rows, 1):
        if (
            not isinstance(row, dict)
            or not REQUIRED_FIELDS <= row.keys()
            or not all(isinstance(row[field], str) and row[field].strip() for field in TEXT_FIELDS)
        ):
            fail("invalid_required_fields", row=index)
            continue
        qa_id = row["qa_id"]
        if not re.fullmatch(r"m1-\d{5}", qa_id) or qa_id in seen_ids:
            fail("invalid_or_duplicate_qa_id", qa_id=qa_id)
        seen_ids.add(qa_id)
        if row["basis"] != "lecture" or not _valid_generator(row["generator"]):
            fail("invalid_provenance", qa_id=qa_id)

        concept_id = row["concept_id"]
        concept = concepts.get(concept_id)
        if concept_id in unseen:
            fail("unseen_concept", qa_id=qa_id, concept_id=concept_id)
        if not concept or row["domain"] != concept["domain"]:
            fail("invalid_concept_or_domain", qa_id=qa_id)
        if row["question_type"] not in QUESTION_TYPES or row["question_form"] not in QUESTION_FORMS:
            fail("invalid_question_category", qa_id=qa_id)
        question = row["question_ko"]
        normalized = normalized_question(question)
        if not HANGUL.search(question) or not normalized:
            fail("invalid_korean_question", qa_id=qa_id)
        else:
            question_index.append((qa_id, normalized, trigrams(normalized)))
        by_concept[concept_id] += 1
        by_type[row["question_type"]] += 1
        by_form[row["question_form"]] += 1
        by_domain[row["domain"]] += 1

        sources = row["evidence"]
        if not isinstance(sources, list) or not sources:
            fail("missing_evidence", qa_id=qa_id)
            sources = []
        for source in sources:
            if (
                not isinstance(source, dict)
                or not isinstance(source.get("file"), str)
                or type(source.get("page")) is not int
                or source["page"] < 1
                or source.get("source") not in ("text_layer", "visual_read")
            ):
                fail("invalid_evidence", qa_id=qa_id)
                continue
            key = page_key(source)
            if forbidden_page(key):
                fail("forbidden_page", qa_id=qa_id)
            elif (*key, source["source"]) not in evidence:
                fail("unsupported_page_or_method", qa_id=qa_id)

        translated, preserved = (row[field] for field in ANSWER_FIELDS)
        for field in ANSWER_FIELDS:
            answer = row[field]
            words = word_count(answer)
            word_counts[field].append(words)
            if not 1 <= words <= WORD_LIMIT or not 1 <= sentence_count(answer) <= SENTENCE_LIMIT:
                fail("answer_length", qa_id=qa_id, field=field)
            if not HANGUL.search(answer):
                fail("missing_korean_answer", qa_id=qa_id, field=field)
        if LATIN.search(translated):
            fail("latin_in_translated_answer", qa_id=qa_id)

        def translate(match: re.Match, qa_id: str = qa_id) -> str:
            term, particle = match["term"], match["particle"]
            ko = translations[term]
            if particle:
                pair = PARTICLE_SLOTS[particle]
                expected = english_particle(term, pair, rules)
                if expected is None or particle != expected:
                    fail("particle_rule", qa_id=qa_id, term=term, particle=particle)
                return ko + korean_particle(ko, pair)
            return ko

        matched_terms = {match["term"].casefold() for match in english.finditer(preserved)}
        if (
            concept
            and concept.get("preserve_english")
            and not _primary_term_present(concept, matched_terms)
        ):
            fail("missing_preserved_term", qa_id=qa_id)
        if LATIN.search(english.sub("", preserved)):
            fail("unmapped_english_in_preserved_answer", qa_id=qa_id)
        projected = english.sub(translate, preserved)
        exact_pairs += projected == translated
        if korean.findall(translated) != korean.findall(projected):
            fail("answer_term_mismatch", qa_id=qa_id)
        comparison = [
            korean.sub(lambda match: markers[match[0]], value) for value in (translated, projected)
        ]
        similarity = SequenceMatcher(None, *comparison, autojunk=False).ratio()
        similarities.append(similarity)
        if similarity < MIN_PAIR_SIMILARITY:
            fail("answer_pair_similarity", qa_id=qa_id, similarity=round(similarity, 4))

    for concept_id, count in by_concept.items():
        if count > MAX_PER_CONCEPT:
            fail("concept_limit", concept_id=concept_id, count=count)
    for (left, left_text, left_grams), (right, right_text, right_grams) in combinations(
        question_index, 2
    ):
        similarity = 2 * len(left_grams & right_grams) / (len(left_grams) + len(right_grams))
        if left_text == right_text:
            fail("duplicate_question", qa_id=right, other_qa_id=left)
        elif similarity >= DUPLICATE_SIMILARITY:
            fail(
                "near_duplicate_question",
                qa_id=right,
                other_qa_id=left,
                similarity=round(similarity, 4),
            )

    return {
        "qa_count": len(rows),
        "by_concept": dict(sorted(by_concept.items())),
        "by_question_type": dict(sorted(by_type.items())),
        "by_question_form": dict(sorted(by_form.items())),
        "by_domain": dict(sorted(by_domain.items())),
        "mean_words": {
            field: round(mean(counts), 2) if counts else None
            for field, counts in word_counts.items()
        },
        "exact_pair_after_translation_count": exact_pairs,
        "min_normalized_pair_similarity": round(min(similarities), 4) if similarities else None,
        "pair_similarity_threshold": MIN_PAIR_SIMILARITY,
        "duplicate_similarity_threshold": DUPLICATE_SIMILARITY,
        "duplicate_similarity_method": "sorensen_dice_character_trigram_set",
        "failure_count": len(failures),
        "failures": failures,
    }


def check_dataset(private_root: Path, dataset: Path) -> dict:
    concept_rows = read_json(private_root / "knowledge/concept_map.json")["concepts"]
    return validate(
        list(read_jsonl(dataset / "qa.jsonl")),
        concepts={row["concept_id"]: row for row in concept_rows},
        unseen=set(read_json(private_root / "evalset/plan_v1.json")["unseen_concepts"]),
        evidence=lecture_evidence(private_root),
        translations=read_json(dataset / "term_translations.json"),
        particle_rules=read_json(private_root / "knowledge/review/particle_rules.json"),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-root", type=Path, default=Path("data_private"))
    parser.add_argument("--dataset", type=Path)
    args = parser.parse_args()
    dataset = args.dataset or args.private_root / "train/m1_lecture_only"
    report = check_dataset(args.private_root, dataset)
    (dataset / "qc.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"{report['qa_count']} QA, {report['failure_count']} QC findings")
    return int(report["failure_count"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
