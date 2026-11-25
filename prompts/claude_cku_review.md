# Claude 검증 지시: CKU(핵심 개념) 내용 검증

검증자: Claude. 작성자(Codex)와 다른 모델이 독립적으로 판정한다.
AGENTS.md의 비공개 경계를 따른다. 모든 입력과 출력은 로컬 `data_private/` 안에서만 다룬다.

## 입력

- `data_private/knowledge/cku_v1.jsonl`: 검증 대상(개념당 한 줄). **수정하지 않는다.**
- `data_private/knowledge/concept_map.json`: 강의 근거 facet과 `lecture_sources`
- `data_private/knowledge/lecture_pages.json`: 페이지 텍스트(`source.file`, `source.page`, `text`)
- `data_private/audit/corpus_v2.json`: 유효한 강의 페이지 목록
- 파일명은 macOS에서 NFD로 저장되어 있을 수 있으므로 비교할 때 `unicodedata.normalize("NFC", ...)`를 쓴다.

## 개념마다 확인할 것

1. **학술적 정확성:** `core_answer_ko`, `definition_ko`, `mechanism_ko`, `purpose_ko`, `limitations_ko`, `formula`에
   사실 오류, 과도한 일반화, 다른 개념과의 혼동이 없는가. 확신이 없으면 `unclear`로 두고 이유를 쓴다.
2. **강의와의 일치:** `sources.lecture`와 `concept_map`의 `lecture_sources` 중 실질 설명 페이지의 텍스트를 직접 읽고,
   CKU가 강의의 정의·표기·범위와 모순되지 않는가. 강의가 다르게 설명하면 `lecture_difference`에 요지를 쓴다.
   (CKU 작성자는 191개 모두 `consistent: true`로 기록했으므로 이 항목을 특히 꼼꼼히 본다.)
3. **`core_answer_ko` 품질:** "X란 무엇인가?"에 직접 답하는가, 핵심이 빠지지 않았는가, 지나치게 모호하지 않은가,
   한국어 1~2문장·30어절 이내인가. 교수님 채점 기준(정확성, 질문 부합성, 간결성)으로 1~5점을 매긴다.
4. **용어 정책:** 지정 전문 용어(NLP, SFT, Tokenizer, LoRA, Embedding, Transformer, Attention 등)를 영어 원어로 유지했는가,
   약어 풀이(`terminology.full_form`)가 **NLP 분야의 뜻**인가, 불필요한 영어를 남발하지 않았는가.
5. **누락:** 시험에서 자주 묻는 핵심 오해(`misconceptions_ko`)나 혼동 개념(`contrast_with`)이 빠졌다면 제안한다.

## 판정

- `correct`: 수정 불필요
- `minor_issue`: 표현·정밀도 문제(의미는 맞음)
- `incorrect`: 사실 오류 또는 강의와 모순
- `unclear`: 검증자가 확신할 수 없음(사람 검토 필요)

## 출력

`data_private/knowledge/review/cku_review_<group>.jsonl`에 개념당 한 줄:

```json
{"concept_id": "...", "verdict": "correct | minor_issue | incorrect | unclear",
 "core_answer_score": 1, "issues": ["..."], "lecture_difference": "... | null",
 "suggested_core_answer_ko": "... | null", "suggested_fixes": {"definition_ko": "..."},
 "suggested_misconceptions_ko": ["..."], "suggested_contrast_with": [{"concept_id": "...", "difference_ko": "..."}],
 "checked_pages": [{"file": "NLP/...", "page": 3}], "reviewer": {"tool": "claude", "model": "<모델명>"}}
```

- 수정안(`suggested_*`)은 실제로 고칠 필요가 있을 때만 쓴다. `suggested_core_answer_ko`도 30어절 이내 1~2문장이어야 한다.
- 개념 설명이나 강의 문장을 `data_private/` 밖에 쓰지 않는다. 공개 문서는 따로 작성하지 않는다.
