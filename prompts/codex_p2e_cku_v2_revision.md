# Codex 작업 지시: P2e CKU v2 수정(Claude 검증 반영)

권장 설정: `gpt-6.2-sol`, reasoning **high**.

---

AGENTS.md를 먼저 읽고 모든 규칙(특히 비공개 경계, 연구 무결성, `llm_teacher` 출처 분리)을 따르라.

## 배경

Codex가 작성한 `data_private/knowledge/cku_v1.jsonl`(191개)을 Claude가 독립적으로 검증했다
(기준: `prompts/claude_cku_review.md`). 검증 결과는 `data_private/knowledge/review/cku_review_all.jsonl`에 있다.

| 판정 | 개념 수 |
|---|---:|
| correct | 135 |
| minor_issue | 55 |
| incorrect | 1 |

반복된 문제 유형:

1. `core_answer_ko`에 핵심 이유나 조건이 빠짐(예: 스케일링의 이유, loss를 어디에 거는지, 무엇이 고정되는지)
2. 강의 설명과의 차이가 있는데 `lecture_alignment.consistent`가 모두 `true`로 기록됨(검증자가 56개에서 차이를 기록)
3. 동의어가 아닌 표현을 alias에 넣음
4. 강의에서 다른 뜻으로 쓰는 한국어 용어와 혼동(예: 강의의 "정규화"는 normalization)
5. `preserve_english: true`인데 core answer에서 한국어로 바꿔 씀
6. `misconceptions_ko`(182개)와 `contrast_with`(159개)가 대부분 비어 있음
7. 단순 언급 페이지의 과다 인용, 실질 설명 페이지 누락
8. `full_form`이 비어 있거나, `writer.reasoning`이 "unconfirmed"로 기록됨

## 작업

### 1. 검증 결과 반영

`cku_review_all.jsonl`의 모든 개념에 대해(verdict가 `correct`여도 수정안이 있으면 포함):

- 검증자의 `issues`와 `suggested_*`를 검토하고 **수용(accept), 일부 수용(partial), 거절(reject)** 중 하나로 결정한다.
- 거절하거나 일부만 수용하면 이유를 쓴다. 검증자 의견이 틀렸다고 판단하면 근거(강의 페이지 또는 열어 본 외부 자료)를 제시한다.
- 결정을 `data_private/knowledge/review/cku_v2_decisions.jsonl`에 개념당 한 줄로 기록한다:
  ```json
  {"concept_id": "...", "review_verdict": "minor_issue",
   "decisions": [{"issue": "...", "decision": "accept | partial | reject", "reason": "..."}],
   "changed_fields": ["core_answer_ko", "lecture_alignment"]}
  ```

### 2. 강의와의 차이 처리

- 검증자가 `lecture_difference`를 기록한 개념은 강의 페이지를 다시 읽고 `lecture_alignment`를 고친다.
  - 강의가 범위를 좁히거나 다른 표현을 쓰면: `consistent: true`로 두되 `lecture_summary`에 강의의 요지와 표기를 쓰고,
    `core_answer_ko`가 강의 표현과 충돌하지 않게 맞춘다.
  - 강의와 실제로 모순되면: `consistent: false`, `difference_note`에 차이를 쓴다.
  - `scope_unverified`나 빈 `lecture_summary`는 남기지 않는다.
- **강의 자료 자체의 오류로 보이는 경우**(검증자가 기록한 수치 표기 1건, RMSNorm 설명 1건 등)는 CKU를 학술적으로
  정확하게 유지하고, `lecture_alignment.lecture_error_note`에 강의 쪽 표기를 기록한다. 강의 오류를 CKU에 옮기지 않는다.
- `incorrect` 판정 1건(`average_precision`)은 강의의 정의를 우선 기준으로 고치고, 일반적인 정의와의 차이를
  `difference_note`에 남긴다.

### 3. 비어 있는 항목 채우기

- 모든 `core` 개념에 `misconceptions_ko`를 최소 1개 채운다. 시험에서 실제로 틀리기 쉬운 오해를 쓴다.
  약어를 다른 분야의 뜻으로 해석하는 오류(예: NLP 외 분야의 같은 약어)가 가능한 개념에는 반드시 포함한다.
- 혼동하기 쉬운 짝이 있는 개념에는 `contrast_with`를 채운다(양쪽 개념 모두에 서로를 기록).
- 검증자의 `suggested_misconceptions_ko`, `suggested_contrast_with`를 우선 검토한다.
- 근거가 없으면 억지로 채우지 않고 빈 값으로 두며, 그 개념 목록을 보고한다.

### 4. 용어와 출처 정리

- alias에서 동의어가 아닌 항목을 제거한다(관련 개념이면 `contrast_with`나 `related_ids`로 옮긴다).
- 강의에서 다른 뜻으로 쓰는 한국어 표기는 alias에서 빼고 `misconceptions_ko`나 `terminology.notes`에 구분을 남긴다.
- `preserve_english: true`인 용어는 `core_answer_ko`에서 영어 원어를 유지한다.
- `full_form`이 있는 약어는 NLP 분야의 풀이를 채운다.
- `sources.lecture`는 **실질 설명 페이지** 위주로 정리한다(단순 언급만 있는 페이지 제거, 빠진 정의 페이지 추가).
  페이지는 `corpus_v2`에 있어야 한다.
- `writer.reasoning`에 실제 설정값을 기록한다(사용자에게 확인).

### 5. 작성 규칙(유지)

- `core_answer_ko`: 한국어 1~2문장, 공백 기준 30어절 이내, 질문에 직접 답하고 핵심 이유를 포함한다. `ktide.metrics`로 확인한다.
- 설명은 바꿔 쓰고(paraphrase), 외부 자료는 실제로 열어 본 것만 출처로 적는다.
- 교수님 공개 질문 11개의 표현이나 답변을 예시로 쓰지 않는다.

## 산출물

- `data_private/knowledge/cku_v2.jsonl`: 수정본(`cku_v1.jsonl`은 덮어쓰지 않는다). 각 줄에 `"version": 2`와
  `"revision": {"based_on": "cku_v1", "review": "cku_review_all", "changed_fields": [...]}`를 추가한다.
- `data_private/knowledge/review/cku_v2_decisions.jsonl`
- `data_private/knowledge/cku_v2_diff_summary.json`: 개념별로 바뀐 필드 목록과 core answer 변경 전후(로컬 검토용)

## 코드, 테스트, 문서

- 반영·비교 스크립트는 `src/ktide/knowledge/` 아래에 만든다. 비공개 내용을 코드나 테스트에 넣지 않는다.
- `tests/test_cku.py`에 v2 검사를 추가한다:
  - 191개 모두 v2가 정확히 하나 있고, 모든 리뷰 항목에 결정 기록이 있음
  - `core_answer_ko`가 30어절 이내 1~2문장
  - `lecture_alignment`에 `scope_unverified`나 빈 `lecture_summary`가 없음
  - `core` 개념의 `misconceptions_ko`가 비어 있지 않음(예외는 사유 기록이 있을 때만)
  - `contrast_with`가 양방향으로 기록됨
  - `sources.lecture` 페이지가 `corpus_v2`에 있음
- `docs/progress/P2e_canonical_knowledge.md`에 v2 집계를 추가한다(집계 수치만):
  수용·일부 수용·거절 수, 바뀐 필드별 개념 수, `consistent: false` 개수, `lecture_error_note` 개수,
  misconceptions·contrast_with 채움 비율 변화, core answer 평균 어절 수.

## 완료 조건

- `uv run pytest -q`, `uv run ruff check src tests` 통과
- 커밋·push 하지 말고, 결과 요약과 **거절한 검증 의견 목록**, 채우지 못한 항목 목록을 보고한 뒤 멈춘다.
  **이후 Claude가 바뀐 부분과 거절 사유를 다시 검증한다.**
