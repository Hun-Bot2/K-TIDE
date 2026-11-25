# Codex 작업 지시: P2g CKU v3 — 공식 교재(SLP) 근거 보강

권장 설정: `gpt-6.2-sol`, reasoning **high**. 수식·표가 이미지인 부분은 이미지 입력 사용.

---

AGENTS.md를 먼저 읽고 따르라(비공개 경계, 연구 무결성, `llm_teacher` 출처 분리).

## 배경

수업의 공식 교재인 Jurafsky & Martin, *Speech and Language Processing*(3판 초안, 2026-08-19 판)의 장 일부가
`Speech-Language/`에 있다. 개념 지도와 겹치는 장만 남겼다(본문 1–9, 11, 14장, 부록 B, C, I).
`Speech-Language/_excluded/`의 파일은 범위 밖이므로 **읽지 않는다.**

현재 CKU v2.1(`data_private/knowledge/cku_v2_1.jsonl`, 199개)은 근거의 대부분이 `model_knowledge`이고,
실제로 열어 본 외부 자료 근거는 거의 없다. 이번 작업은 교재를 근거로 CKU를 **확인·교정·보강**하는 것이다.

이 교재는 "All rights reserved"이다. 원문을 길게 옮기지 않고 바꿔 쓰며, 교재에서 파생한 내용은
`data_private/` 밖에 쓰지 않는다.

## 작업 1. 교재 텍스트 준비

- 각 PDF의 텍스트를 페이지 단위로 추출해 `data_private/external/slp/pages.jsonl`에 저장한다:
  `{"file": "Speech-Language/3.pdf", "chapter": "3", "page": 5, "section": "3.2 ...", "text": "..."}`
  (절 제목은 페이지 텍스트에서 확인되는 경우만 채운다.)
- 수식·표가 이미지라 텍스트로 확인되지 않는 페이지는 표시만 하고, 그 페이지가 CKU 근거로 필요할 때만 이미지를 확인한다.

## 작업 2. 개념별 교재 근거 대응

CKU v2.1의 각 개념에 대해 교재에서 **실질적으로 설명하는 절과 페이지**를 찾는다(단순 언급 제외).

- 결과: `data_private/external/slp/concept_evidence.jsonl`
  `{"concept_id": "...", "slp_sources": [{"file": "...", "chapter": "3", "section": "3.4", "page": 12, "role": "definition | mechanism | formula | example | limitation"}], "not_in_slp": false}`
- 교재에서 찾을 수 없는 개념(강의에만 있는 내용 등)은 `not_in_slp: true`로 둔다. 억지로 대응하지 않는다.

## 작업 3. CKU 확인·교정 (CKU v3)

교재 근거가 있는 개념마다 CKU 필드를 교재와 대조한다.

1. **일치하면** 해당 필드의 `basis`에 `slp_textbook`을 추가하고 `sources.slp`에 절·페이지를 기록한다.
   (`model_knowledge`만 있던 필드가 교재로 확인되면 `model_knowledge`를 `slp_textbook`으로 바꾼다.)
2. **틀리거나 부정확하면** 교재 기준으로 고치고, 변경 전·후와 근거를 기록한다.
3. **강의와 교재가 다르면** 과제 채점 기준에 맞춰 **강의 설명을 우선**하고, 교재와의 차이를
   `lecture_alignment.textbook_note`에 쓴다(예: Average Precision의 분모, 표기 차이). 어느 쪽이 맞는지 임의로 판단하지 않는다.
4. **교재로 보강할 수 있는 빈 항목**(`mechanism_ko`, `limitations_ko`, `formula`, `misconceptions_ko`, `contrast_with`)은 교재 근거로 채운다.
   이때 `basis`는 `slp_textbook`이다.
5. `core_answer_ko`는 교재와 모순되지 않는지 확인하고, 필요할 때만 고친다(한국어 1~2문장, 30어절 이내,
   `particle_rules.json`의 조사 규칙, 영어 전문 용어 유지). 혼동 행렬 용어(True/False Positive/Negative)는 영어로 쓴다.
6. 교재에는 있지만 개념 지도에 없는 개념은 추가하지 않는다. `data_private/external/slp/out_of_scope_candidates.json`에
   후보로만 기록한다(강의에도 있는지 확인한 결과와 함께).

## 산출물

- `data_private/knowledge/cku_v3.jsonl` (v2.1은 덮어쓰지 않는다). 각 줄에 `"version": 3`,
  `"revision": {"based_on": "cku_v2_1", "changes": ["slp_grounding", ...], "changed_fields": [...]}`
- `data_private/knowledge/review/cku_v3_changes.jsonl`: 개념별 변경 필드, 변경 전·후, 근거(교재 절·페이지), 변경 사유
- `data_private/external/slp/pages.jsonl`, `concept_evidence.jsonl`, `out_of_scope_candidates.json`

## 코드, 테스트, 문서

- 추출·대응·검증 스크립트는 `src/ktide/knowledge/` 아래에 둔다. 교재 문장이나 강의 문장을 코드·테스트에 넣지 않는다.
- `tests/test_cku.py`에 검사를 추가한다:
  - `cku_v3`가 개념 지도의 모든 개념을 정확히 한 번씩 포함
  - `basis`에 `slp_textbook`이 있으면 `sources.slp`가 비어 있지 않고, 그 파일이 `Speech-Language/`의 유지 대상 파일이며 페이지가 범위 안
  - `_excluded/` 파일을 근거로 쓰지 않음
  - `core_answer_ko` 30어절 이내 1~2문장, 조사 규칙 일치
- `docs/progress/P2g_slp_grounding.md`에 **집계 수치만** 쓴다: 교재 근거가 있는 개념 수, `not_in_slp` 수,
  `basis` 분포 변화(v2.1 → v3), 교정한 필드 수(필드별), 강의·교재 차이를 기록한 개념 수, 범위 밖 후보 수.
  교재 문장, 개념 설명, 파일 경로 외의 내용은 쓰지 않는다.

## 완료 조건

- `uv run pytest -q`, `uv run ruff check src tests` 통과
- 커밋·push 하지 말고, 결과 요약, 교재 기준으로 **내용을 고친 개념 목록**, 강의·교재 차이 목록을 보고한 뒤 멈춘다.
  이후 Claude가 바뀐 개념을 검증한다.
