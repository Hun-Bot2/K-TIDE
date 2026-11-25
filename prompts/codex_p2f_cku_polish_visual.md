# Codex 작업 지시: P2f CKU 조사 교정, 차이 설명 정리, 이미지 페이지 용어 추출

권장 설정: `gpt-6.2-sol`, reasoning **high**, 이미지 입력 사용.

---

AGENTS.md를 먼저 읽고 따르라. **AGENTS.md §4가 갱신되어, 작업 지시문이 요청한 이미지 판독은 허용된다.**
P2e에서 `awaiting_visual_rule_confirmation` 상태로 멈춘 이미지 판독을 이 지시문에 따라 진행한다.

## 작업 1. 영어 용어 뒤 한국어 조사 교정

CKU v2에서 한국어 용어를 영어 원어로 바꾸면서 조사가 기계적으로 남아 문법 오류가 생겼다.
`core_answer_ko`는 학습 데이터의 정답이 되므로 반드시 고친다.

- 예(틀림): "Term Frequency은", "Gradient Descent은", "Leakage은", "Matrix은" → 모두 "는"이 맞다.
- 예(맞음): "Embedding은", "Attention은", "Sampling은", "Logit을" (한국어로 읽을 때 받침으로 끝남)

규칙:

1. 조사는 **영어 용어를 한국어로 읽었을 때 마지막 소리**로 고른다.
   받침으로 끝나면 `은/이/을/과`, 모음으로 끝나면 `는/가/를/와`. 약어는 알파벳 이름으로 읽는다
   (예: SFT[에스에프티]는, LoRA[로라]는, RNN[알엔엔]은, LLM[엘엘엠]은, BPE[비피이]는).
2. 대상 필드: `core_answer_ko`, `definition_ko`, `mechanism_ko`, `purpose_ko`, `limitations_ko`,
   `misconceptions_ko`, `contrast_with[].difference_ko`, `lecture_alignment.lecture_summary`.
3. 조사 외의 단어와 의미는 바꾸지 않는다. 문장이 어색하면 고치되 변경 이유를 기록한다.
4. 읽는 방식이 갈리는 용어(예: 숫자·기호가 섞인 표기)는 한 가지로 정하고 `data_private/knowledge/review/particle_rules.json`에
   용어별 읽기와 조사를 기록해 이후 QA 생성에도 같은 규칙을 쓴다.
5. 교정 결과를 `data_private/knowledge/review/particle_fixes.jsonl`에 기록한다:
   `{"concept_id": "...", "field": "...", "before": "...", "after": "...", "term": "...", "reading": "..."}`

## 작업 2. 판에 박힌 차이 설명 정리

`lecture_alignment.difference_note`에 같은 템플릿 문장이 30개 개념에 반복되어 있다
("강의의 예시·표기·적용 범위를 다시 확인했다..."로 시작).

- 강의와 실제 차이가 있으면 그 차이를 구체적으로 쓴다(무엇이 어떻게 다른지, 근거 페이지).
- 차이가 없으면 `difference_note`를 `null`로 둔다.
- 템플릿 문장을 남기지 않는다.

## 작업 3. 이미지 페이지 용어 추출 (P2e 작업 1)

`prompts/codex_p2e_canonical_knowledge.md`의 **작업 1**을 그대로 수행한다.
대상은 `data_private/extracted/visual_queue_v2.json`의 270쪽이며, 결과는 `data_private/extracted/visual_terms.jsonl`에 저장한다.

- 전체를 옮겨 적지 않고 개념, 역할, 강조점, 핵심 수식만 기록한다. 보이는 것만 기록한다.
- `skip_regions`는 건너뛰고, `figure_index.json`의 반복 그림은 대표 페이지에서 한 번만 본다.
- 수식은 확대해서 첨자·부호를 다시 확인한다.
- 배치마다 `cku_progress.json`의 `visual` 항목(처리 수, 남은 페이지)을 갱신한다. 중단되면 이어서 진행한다.
- **일부만 처리하고 끝내지 않는다.** 270쪽 전부를 처리한다.

이미지에서 나온 결과로:

- 새 개념(강의에 실제로 나오고 개념 지도에 없는 것)은 `concept_map.json`에 추가하고(추가 전 백업),
  CKU를 v2와 같은 형식으로 작성한다. 새 CKU는 `"review_status": "unverified"`로 표시한다(Claude가 검증).
- 기존 개념의 강의 근거가 이미지에서 확인되면 `sources.lecture`와 `lecture_alignment`를 보강한다.

## 산출물

- `data_private/knowledge/cku_v2_1.jsonl`(v2는 덮어쓰지 않는다). 각 줄에 `"version": "2.1"`,
  `"revision": {"based_on": "cku_v2", "changes": ["particles", "difference_note", "visual_evidence", "new_concept"]}`
- `data_private/knowledge/review/particle_fixes.jsonl`, `particle_rules.json`
- `data_private/extracted/visual_terms.jsonl`, 갱신된 `cku_progress.json`
- `data_private/knowledge/cku_v2_1_new_concepts.json`: 새 개념과 근거 페이지, 기각한 후보와 사유

## 코드, 테스트, 문서

- 스크립트는 `src/ktide/knowledge/` 아래. 비공개 내용을 코드나 테스트에 넣지 않는다.
- `tests/test_cku.py`에 검사를 추가한다:
  - `cku_v2_1`이 `concept_map`의 모든 개념을 정확히 한 번씩 포함
  - `particle_rules.json`에 등록된 용어 뒤의 조사가 규칙과 일치
  - `difference_note`에 템플릿 문장이 없음
  - 이미지 판독 대상 270쪽이 모두 `visual_terms.jsonl`에 있음
  - `core_answer_ko` 30어절 이내 1~2문장
- `docs/progress/P2e_canonical_knowledge.md`에 v2.1 집계를 추가한다(집계 수치만):
  조사 교정 건수(필드별), 정리한 차이 설명 수, 이미지 판독 페이지 수·신뢰도 분포, 새 개념 수, 근거가 보강된 개념 수.

## 완료 조건

- `uv run pytest -q`, `uv run ruff check src tests` 통과
- 커밋·push 하지 말고, 결과 요약, 새 개념 목록, 판독하지 못한 페이지를 보고한 뒤 멈춘다.
