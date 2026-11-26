# Codex 작업 지시: P2e 핵심 개념 정리(Canonical Knowledge Units, Teacher 작성)

권장 설정: `gpt-6.2-sol`, reasoning **high**(개념 정확도가 핵심), 이미지 판독이 필요한 부분은 이미지 입력 사용.

---

AGENTS.md를 먼저 읽고 모든 규칙(특히 비공개 경계와 연구 무결성)을 따르라.

## 목적과 역할 분담

강의 자료의 텍스트만으로는 개념 설명이 비어 있거나 불완전하다. 이번 작업에서 대형 모델(Teacher)이
강의에 나온 개념마다 **정확한 핵심 개념**을 작성한다. 원칙은 다음과 같다.

- **강의 자료는 범위의 기준이다:** 어떤 개념이 수업에 나왔는지, 교수님이 무엇을 강조했는지는 강의에서 가져온다.
- **정확성은 Teacher와 외부 근거로 보완한다:** 설명은 학술적으로 정확하고 완전해야 한다.
- **출처를 분리한다:** 강의에서 확인한 내용(`concept_map.json`의 facet)은 그대로 두고, Teacher가 작성한 내용은
  별도 파일(CKU)에 저장한다. 두 층을 섞거나 덮어쓰지 않는다. (나중에 Lecture-only와 Enriched 학습을 비교하기 위함)
- **작성과 검증을 다른 모델이 맡는다:** 이 작업에서 Codex는 **작성자**다. 검증은 Claude가 별도로 수행한다.
  Codex는 자체 점검(형식, 길이, 근거 표기)만 하고, 내용의 최종 판정은 하지 않는다.

## 작업 0. P2d-0 정리(먼저 수행)

P2d-0 검증에서 남은 항목을 먼저 정리한다.

1. `page_filter.jsonl`에서 사용자 검수가 끝난 페이지의 `needs_human_review`를 `false`로 고치고,
   검수 결과(`keep`/`exclude`)가 반영되었는지 확인한다. 아직 검수하지 않은 페이지만 `true`로 남긴다.
2. `prompts/codex_p2d0_dedupe_filter.md`에서 요구한 테스트를 추가한다
   (전체 페이지 1회 포함, `duplicate_of` 연쇄 없음, 사용자 라벨 충돌 없음, `corpus_v2`와 keep 일치,
   반복 그림 대표만 판독 대상에 포함).
3. `docs/progress/P2d0_dedupe_filter.md`에 빠진 집계를 추가한다: 제외 사유별 페이지 수(파일 간 중복,
   빌드 단계, 반복 슬라이드, 각 범주), 판본 관계별 파일 쌍 수, 반복 그림 묶음 수, 요소 단위 제외 수,
   코퍼스 변화(1,518 → 1,086), 시각 판독 대상 변화(480 → 270). 파일명과 내용은 쓰지 않는다.

## 작업 1. 이미지 페이지 용어 추출(가벼운 판독)

`data_private/extracted/visual_queue_v2.json`의 270쪽을 대상으로, 전체를 옮겨 적지 않고 **개념과 강조점만** 뽑는다.

- 페이지마다: 페이지가 설명하는 개념(기존 `concept_id` 또는 새 용어), 역할(정의, 원리, 수식, 도식, 비교, 예시),
  교수님이 강조한 점(굵은 글씨, 색, 박스, 반복 등으로 강조된 내용)을 짧게 기록한다.
- 수식이 개념의 핵심이면 수식만 정확히 옮긴다(첨자·부호를 확대해서 재확인).
- `skip_regions`는 건너뛰고, `figure_index.json`의 반복 그림은 대표 페이지에서 한 번만 본다.
- 보이는 것만 기록한다. 추측하지 않는다.
- 결과: `data_private/extracted/visual_terms.jsonl`
  `{"source": {...}, "concepts": [{"concept_id": "... | null", "new_term": "... | null", "role": "...", "emphasis": "..."}], "formula": "... | null", "confidence": "high | medium | low"}`
- 새 용어는 개념 지도에 추가할 후보로 모은다(작업 2에서 함께 다룬다).

## 작업 2. 핵심 개념 작성(CKU)

대상: `concept_map.json`의 모든 개념 + 작업 1에서 나온 새 개념 후보(강의에 실제로 나온 것만).
`coverage_depth`가 `core`인 개념부터 영역(D01~D10) 순서로 처리한다.

개념마다 아래 항목을 작성한다.

| 필드 | 내용 |
|---|---|
| `core_answer_ko` | "X란 무엇인가?"에 대한 모범 답. **한국어 1~2문장, 공백 기준 30어절 이내**, 핵심만. |
| `definition_ko` | 정확한 정의(2~3문장). |
| `mechanism_ko` | 동작 원리 또는 계산 방식. 해당 없으면 null. |
| `purpose_ko` | 왜 쓰는지, 무엇을 해결하는지. |
| `limitations_ko` | 한계·단점. 해당 없으면 null. |
| `misconceptions_ko` | 흔한 오해와 바른 설명(0~3개). 특히 약어를 다른 분야 뜻으로 해석하는 오류를 포함한다. |
| `contrast_with` | 혼동하기 쉬운 개념과 차이(예: Precision vs Recall). `concept_id`와 한 줄 차이. |
| `formula` | 핵심 수식(LaTeX). 강의 표기를 우선한다. 해당 없으면 null. |
| `terminology` | `canonical_term`, `full_form`(약어 풀이, **NLP 분야의 뜻**), `preserve_english`, `aliases_ko`, `aliases_en` |
| `lecture_alignment` | `consistent`(true/false), 강의의 설명 요지, 차이가 있으면 `difference_note` |
| `basis` | 각 항목의 근거 종류: `lecture`, `external_reference`, `model_knowledge` (복수 가능) |
| `sources` | `lecture`: 강의 페이지 목록, `external`: 실제로 열어 본 외부 자료만 `{title, section, url}` |
| `confidence` | `high | medium | low`와 낮은 이유 |
| `open_questions` | 검증자가 꼭 확인해야 할 점 |

작성 규칙:

- **강의와 맞춘다.** 강의(텍스트, `visual_terms.jsonl`, `concept_map.json` facet)에서 정의·표기·범위를 먼저 확인하고,
  그와 모순되지 않게 쓴다. 강의 설명이 학술적으로 부정확하거나 좁다고 판단되면 고치지 말고
  `lecture_alignment.difference_note`에 기록한다.
- **외부 근거는 실제로 확인한 것만 적는다.** 자료를 열어 보지 않았다면 출처를 만들지 말고 `basis`에 `model_knowledge`라고 쓴다.
  참고할 수 있는 공개 자료: Speech and Language Processing(3판 초안), Dive into Deep Learning, Hugging Face LLM Course,
  원 논문(Transformer, BERT, LoRA 등). 문장을 복사하지 말고 바꿔 쓴다.
- **용어 정책:** 설명은 한국어로 쓰고, 지정 전문 용어(NLP, SFT, Tokenizer, LoRA, Embedding, Transformer, Attention 등)는
  영어 원어를 유지한다. 불필요한 영어 단어를 늘리지 않는다.
- **`core_answer_ko`는 학습·평가의 기준 답이 된다.** 정확성을 우선하고, 질문의 핵심에 직접 답하며, 인사말·서론을 넣지 않는다.
  30어절 제한은 `ktide.metrics.word_count`로 확인한다.
- 교수님 공개 질문 11개의 표현이나 저장된 답변을 예시로 쓰거나 복사하지 않는다.

## 산출물

- `data_private/knowledge/cku_v1.jsonl`: 개념당 한 줄
  ```json
  {"concept_id": "...", "provenance": "llm_teacher",
   "writer": {"tool": "codex", "model": "<정확한 모델명>", "reasoning": "high", "date": "YYYY-MM-DD"},
   "core_answer_ko": "...", "definition_ko": "...", "mechanism_ko": "...", "purpose_ko": "...",
   "limitations_ko": "...", "misconceptions_ko": ["..."], "contrast_with": [{"concept_id": "...", "difference_ko": "..."}],
   "formula": "...", "terminology": {...}, "lecture_alignment": {...}, "basis": {...}, "sources": {...},
   "confidence": {"level": "high", "reason": ""}, "open_questions": []}
  ```
- `data_private/knowledge/cku_v1_new_concepts.json`: 작업 1·2에서 추가한 개념(강의 근거 포함)과 기각한 후보(사유)
- `data_private/knowledge/cku_progress.json`: 처리한 개념 수, 남은 개념, 마지막 처리 위치(중단 시 재개용)
- `concept_map.json`은 새 개념 추가 외에는 수정하지 않는다(추가 전 `concept_map.p2d0.json`으로 백업).

## 코드, 테스트, 문서

- CKU 스키마 검증과 통계 스크립트는 `src/ktide/knowledge/` 아래에 만든다. 비공개 내용을 코드나 테스트에 넣지 않는다.
- `tests/`에 검사를 추가한다:
  - 모든 `concept_map` 개념에 CKU가 정확히 하나 있음
  - 필수 필드 존재, `provenance == "llm_teacher"`
  - `core_answer_ko`가 30어절 이내이고 1~2문장(`ktide.metrics`의 함수 사용)
  - `sources.lecture`의 페이지가 `corpus_v2`에 있음
  - `basis`에 `external_reference`가 있으면 `sources.external`이 비어 있지 않음
- `docs/progress/P2e_canonical_knowledge.md`에 **집계 수치만** 쓴다: 개념 수(영역별), 새로 추가한 개념 수,
  basis 분포, confidence 분포, 강의와 불일치(`consistent == false`) 개수, `core_answer_ko` 평균 어절 수,
  이미지 판독 페이지 수. 개념 설명은 쓰지 않는다.

## 완료 조건

- 작업 0 완료, 이미지 판독 대상 270쪽 처리 완료, 모든 개념에 CKU 작성 완료
- `uv run pytest -q`, `uv run ruff check src tests` 통과
- 커밋·push 하지 말고, 결과 요약, confidence가 low인 개념, 강의와 불일치한 개념 목록을 보고한 뒤 멈춘다.
  **이후 Claude가 `cku_v1.jsonl`을 검증한다.**
