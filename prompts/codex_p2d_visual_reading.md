# Codex 작업 지시: P2d 이미지 페이지 판독 완료와 개념 지도 갱신

권장 설정: `gpt-6.2-sol`, reasoning **medium 이상**, 이미지 입력 사용.

---

AGENTS.md를 먼저 읽고 모든 규칙(특히 비공개 경계와 연구 무결성)을 따르라.
이 작업은 P2c(`prompts/codex_p2c_concept_map_completion.md`)와 P2d-0(`prompts/codex_p2d0_dedupe_filter.md`)의 후속이다.

**입력 코퍼스는 P2d-0의 `data_private/audit/corpus_v2.json`이고, 시각 판독 대상은 `data_private/extracted/visual_queue_v2.json`이다.**
아래 본문의 "480쪽", "465쪽", "후보 코퍼스"는 모두 이 v2 기준으로 바꿔 읽는다.
P2d-0에서 이미 `exclude`된 페이지(중복, 표지, 목차 등)는 판독하거나 라벨링하지 않는다.
단계 1(썸네일 분류)은 P2d-0에서 결정되지 않은 페이지에만 적용한다.
`page_filter.jsonl`의 `skip_regions`는 판독하지 않는다. `data_private/extracted/figure_index.json`의 반복 그림은
대표 페이지에서 **한 번만** 판독하고, 다른 등장 위치는 그 `figure_id`를 참조한다. 기존 파이프라인
(`src/ktide/knowledge/`)과 편집용 TSV를 확장하고, 결과를 덮어쓰기 전에 `concept_map.p2c.json`으로 백업하라.

## 배경: P2c 검증에서 발견된 문제

1. 시각 판독 대상 480쪽 중 15쪽(3%)만 판독했고 465쪽이 대기 중이다. 판독한 15쪽도 대부분 표지·목차다.
2. 텍스트 레이어가 0자인 강의 파일(58쪽)은 1쪽만 판독되었고, 이 파일에서 나온 근거는 도식 1건(`figure_only`)뿐이다.
   한국어 강의 파일들도 파일당 facet 근거가 1~6개뿐이다. "facet 0건 파일" 지표는 형식상으로만 충족됐다.
3. high 신뢰도로 표시된 판독에서도 수식 첨자 오류(예: `b^{[2]}`를 `b^{[1]}`로 기록)가 있었다.
4. `coverage_stats.pages_substantive`를 일부 수동 표시 페이지에서만 세어, 비중이 큰 개념(예: Attention,
   BERT)이 실제보다 낮게 집계됐다. 그 결과 core 34개, supporting 120개로 분포가 왜곡됐다.

**이번 작업은 일부 페이지만 처리하고 끝내지 않는다.** 대상 페이지 전체를 처리할 때까지 배치 단위로 계속 진행한다.
한 번에 끝낼 수 없으면 진행 상태 파일에 기록하고, 이어서 재개할 수 있게 만든다(아래 "진행 관리").

## 단계 1. 썸네일 분류(Triage) — 대기 중인 465쪽 전부

1. 렌더링한 페이지 이미지의 해시(지각 해시 등)로 **완전히 같거나 거의 같은 페이지**(반복되는 표지, 목차, 구분 슬라이드)를
   묶고, 묶음마다 대표 페이지 하나만 분류한다.
2. 각 페이지를 아래 중 하나로 분류한다.
   - `new_content`: 텍스트 레이어에 없는 개념 설명·수식·도식·표가 있음
   - `duplicate_of_text`: 같은 내용이 다른 페이지의 텍스트 레이어로 이미 확보됨(그 페이지 출처를 기록)
   - `structural`: 표지, 목차, 구분 슬라이드, 참고문헌
   - `decorative`: 장식용
   - `exercise_or_code`: 실습 지시, 코드 실행 결과(개념 설명이 없으면 이 분류)
3. 결과를 `data_private/extracted/visual_triage.jsonl`에 저장한다:
   `{"source": {...}, "sha256": "...", "image_hash": "...", "group_id": "...", "label": "...", "duplicate_of": [{"file": ..., "page": ...}], "note": "..."}`
4. 판단이 애매하면 `new_content`로 분류한다(재현율 우선).

## 단계 2. 정밀 판독 — `new_content` 전부

1. 우선순위: 텍스트 레이어 0자 파일 → 한국어·혼합 파일 → 나머지.
2. 200 dpi 이상으로 렌더링하고, 회전된 페이지는 회전을 보정해서 읽는다. 작은 글씨와 수식은 영역을 확대해 다시 읽는다.
3. 결과는 기존 `visual_transcripts.jsonl` 형식으로 추가한다(이미 판독한 15쪽은 다시 판독하지 않되,
   `confidence`가 medium 이하인 페이지는 다시 읽는다).
4. **보이는 것만 기록한다.** 도식의 의미를 추론하거나 외부 지식으로 빈칸을 채우지 않는다.
5. **수식 재확인:** 수식이 있는 페이지는 판독 후 수식 영역만 확대해 한 번 더 대조한다. 첨자, 위첨자, 부호,
   괄호를 특히 확인한다. 고친 내용이 있으면 `corrections`에 기록한다.

## 단계 3. 판독 정확도 자체 점검

- 정밀 판독 페이지 중 **무작위 10%(최소 20쪽)** 를 시드를 기록해 뽑고, 원본 이미지를 다시 보며 전사와 대조한다.
- 오류를 유형별(글자, 수식 기호, 누락, 도식 관계)로 세어 `data_private/extracted/visual_qc.json`에 기록하고, 오류는 고친다.
- 사람 검토용으로 그중 10쪽의 (이미지 경로, 전사)를 `data_private/extracted/visual_qc_human_sample.json`에 남긴다.

## 단계 4. 페이지별 주제 라벨 — 후보 코퍼스의 모든 페이지

`coverage_stats`를 정확하게 만들기 위해 페이지 단위로 주제를 붙인다.

1. 후보 코퍼스의 모든 고유 페이지(SHA-256·페이지 기준)에 대해, 텍스트 레이어와 판독 결과를 근거로
   그 페이지가 **실질적으로 설명하는 개념**을 0~3개 붙인다(`main_concepts`). 단순 언급은 붙이지 않는다.
   설명하는 개념이 지도에 없으면 새 개념 후보로 기록한다.
2. 각 라벨에 역할을 붙인다: `definition | mechanism | formula | example | figure | comparison | limitation`.
3. 결과를 `data_private/knowledge/page_topics.jsonl`에 저장한다:
   `{"source": {...}, "sha256": "...", "evidence": "text_layer | visual_read | both", "main_concepts": [{"concept_id": "...", "role": "..."}]}`
4. `coverage_stats`를 이 파일에서 다시 계산한다:
   - `pages_substantive`: 그 개념이 `main_concepts`에 있는 고유 페이지 수
   - `files`: 그 페이지들이 속한 고유 파일 수(SHA-256 기준)
   - `pages_mention`: 기존 표기 탐지 페이지 중 `main_concepts`에 없는 페이지 수
   - `coverage_depth` 규칙은 P2c와 같다(core: `pages_substantive >= 3` 또는 `files >= 2`, supporting: 1~2, mention_only: 0).

## 단계 5. 개념 지도 갱신

1. 새로 판독한 내용을 근거로 facet을 채우거나 보강한다(P2c 작업 B와 같은 규칙: paraphrase, 영어 전문 용어 유지,
   근거가 없으면 `missing`, 자료마다 설명이 다르면 `alternatives`).
2. 한국어 강의 자료의 설명을 우선 근거로 추가한다. 영어 자료와 설명이 다르면 둘 다 남긴다.
3. 단계 2·4에서 나온 새 개념 후보를 검토해 추가하거나 기각(사유 기록)한다.
4. 완료 기준은 P2c와 같다: `core` 개념은 `definition`과 `mechanism`·`purpose` 중 하나 이상이 stated 또는 partial,
   `supporting` 개념은 `definition`이 최소 partial. 미충족은 사유와 함께 기록한다.

## 진행 관리

- `data_private/extracted/p2d_progress.json`에 단계별 처리 수, 남은 페이지 목록, 마지막 처리 위치를 저장한다.
- 배치(예: 30~50쪽)마다 진행 상태를 갱신한다. 중단되면 이 파일을 읽고 이어서 진행한다.
- 작업 중간에 사용자에게 보고할 때도 남은 페이지 수를 함께 알린다.

## 산출물

- `data_private/extracted/visual_triage.jsonl`, `visual_transcripts.jsonl`(추가분), `visual_qc.json`,
  `visual_qc_human_sample.json`, `p2d_progress.json`
- `data_private/knowledge/page_topics.jsonl`
- `data_private/knowledge/concept_map.json`(schema_version 3: `page_topics` 기반 `coverage_stats`), 백업 `concept_map.p2c.json`
- `data_private/knowledge/concept_map_checks.json` 갱신:
  `visual_read_summary`(대기 0쪽이 목표), `triage_summary`, `qc_summary`, `added_concepts`, `rejected_candidates`, `open_issues`
- `data_private/knowledge/review_sample_p2d.json`: 이번에 새로 채운 facet 중 무작위 20개(시드 기록)

## 코드, 테스트, 문서

- 페이지 해시, 그룹핑, 렌더링, 통계 계산은 `src/ktide/knowledge/` 스크립트로 만든다.
  비공개 내용(강의 문장, 판독 결과, 파일명)을 코드나 테스트에 넣지 않는다.
- `tests/test_concept_map.py`에 검사를 추가한다:
  - 시각 판독 대상 페이지가 모두 triage되었고, `new_content` 페이지는 모두 판독됨(대기 0쪽)
  - `page_topics.jsonl`이 후보 코퍼스의 모든 고유 페이지를 포함함
  - `coverage_stats`가 `page_topics.jsonl`에서 재계산한 값과 같음
  - `main_concepts`의 concept_id가 모두 개념 지도에 존재함
- `docs/progress/P2d_visual_reading.md`에 **집계 수치만** 쓴다: triage 분류별 페이지 수, 판독 페이지 수,
  QC 오류율(유형별), P2c 대비 개념 수·영역별 개수·coverage_depth 분포·facet status 분포·evidence 분포 변화.
  파일명, 개념 설명, 판독 내용은 쓰지 않는다.

## 완료 조건

- 시각 판독 대기 페이지 0쪽(판독 불가 페이지는 사유와 함께 별도 집계)
- 후보 코퍼스 전체 페이지에 `page_topics` 라벨이 있음
- `uv run pytest -q`, `uv run ruff check src tests` 통과
- 커밋·push 하지 말고, 결과 요약과 `open_issues`, 사람 검토 표본 위치(`visual_qc_human_sample.json`,
  `review_sample_p2d.json`)를 보고한 뒤 멈춘다.
