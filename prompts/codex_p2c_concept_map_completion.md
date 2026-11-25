# Codex 작업 지시: P2c 개념 지도 보완

권장 설정: `gpt-6.2-sol`, reasoning **medium 이상**. 이미지 판독이 포함되므로 이미지 입력을 사용한다.

---

AGENTS.md를 먼저 읽고 모든 규칙(특히 비공개 경계와 연구 무결성)을 따르라.
이 작업은 P2b(`prompts/codex_p2b_concept_map.md`)의 결과물인 `data_private/knowledge/concept_map.json`을
보완하는 작업이다. 기존 파이프라인(`src/ktide/knowledge/extract.py`, `build.py`, 편집용 TSV)을
확장하는 방식으로 진행하고, 기존 결과를 덮어쓰기 전에 `concept_map.p2b.json`으로 백업하라.

## 배경: P2b 검증에서 발견된 문제

1. 개념 176개 중 정의(definition)가 채워진 개념은 35개뿐이다. 개념마다 채워진 facet이 대개 1개이고,
   전체 facet의 86%가 `missing`이다. 이후 평가셋의 Reference Answer 근거로 쓰기에 부족하다.
2. 정리된 facet이 하나도 없는 파일이 12개(약 520쪽)이다. 대부분 한국어로 작성된 강의 자료이며,
   이 수업의 출제 방식에 가장 가까울 수 있는 자료다.
3. 텍스트 레이어가 거의 없는 이미지 위주 페이지가 많다. 한 파일은 전체 페이지에서 텍스트가 0자다.
4. `coverage_depth`가 "facet을 채웠는가"로 결정되어, 강의에서 비중이 큰 개념(예: Transformer,
   LLM, GPT, Neural Network, Quantization)이 `mention_only`로 분류됐다.
5. 강의에 있으나 개념 지도에 없는 후보: ZeRO·분산 학습, gradient checkpointing, PPO, T5,
   vanishing gradient, special token·`[CLS]` 토큰, Tokenizer(구성 요소).
6. `created_by.model`이 정확한 모델명이 아니다.

## 작업 A. 이미지 위주 페이지 판독

1. 대상 페이지를 스크립트로 선정한다. 아래 조건 중 하나라도 만족하면 대상이다.
   - 텍스트 레이어의 한글·영문 글자가 80자 미만인 페이지
   - P2에서 우선 시각 검토 후보로 분류된 페이지
   - 위 2번 문제의 "facet 0건 파일"에 속한 페이지 중 정보성 이미지·다이어그램 후보 페이지
   후보 코퍼스(`p2_corpus_draft.json`)에서 제외된 페이지와 SHA-256 중복 파일은 제외한다.
2. 우선순위: facet 0건 파일 → 한국어·혼합 파일 → 나머지.
3. 페이지를 150~200 dpi PNG로 렌더링하여 `data_private/extracted/page_images/`에 저장하고,
   이미지를 직접 보고 판독한다.
4. 결과를 `data_private/extracted/visual_transcripts.jsonl`에 한 줄에 한 페이지씩 저장한다.

```json
{"source": {"file": "NLP/...", "page": 3}, "sha256": "...", "method": "visual_read",
 "model": "<정확한 모델명>", "transcript": "페이지에 보이는 텍스트를 그대로 옮긴 것(수식은 LaTeX 형태)",
 "figure_description": "도식에 보이는 요소와 화살표 관계만 기술", "confidence": "high | medium | low",
 "unreadable": "읽을 수 없었던 부분과 이유"}
```

   - **보이는 것만 기록한다.** 도식의 의미를 추론하거나 외부 지식으로 빈칸을 채우지 않는다.
   - 글씨가 작으면 확대해서 다시 읽고, 그래도 읽을 수 없으면 `unreadable`에 남긴다.
   - 장식용 페이지는 `transcript`를 비우고 `figure_description`에 "장식용"이라고만 쓴다.
5. 판독한 페이지에서 **새 개념을 bottom-up으로 다시 찾는다**(P2b 절차 2~3과 같은 기준).

## 작업 B. Facet 채우기

1. 근거로 텍스트 레이어와 `visual_transcripts.jsonl`을 모두 사용한다.
2. **완료 기준:** `core` 개념은 모두 `definition`과, `mechanism`·`purpose` 중 하나 이상이
   `stated` 또는 `partial`이어야 한다. `supporting` 개념은 `definition`이 최소한 `partial`이어야 한다.
   근거가 정말 없으면 `missing`으로 두고 `enrichment_needed`에 이유를 쓴다(외부 지식으로 채우지 않는다).
3. 한 facet에 근거 페이지를 여러 개 둘 수 있다. 가능하면 한국어 강의 자료와 영어 강의 자료의
   근거를 모두 붙인다.
4. 자료마다 설명이 다르면(범위, 강조점, 표기) 대표 설명을 `text_ko`에 두고, 다른 설명을
   `alternatives`에 남긴다. 어느 쪽이 맞는지 판단하지 않는다.
5. 각 facet에 근거 종류를 남긴다: `evidence: "text_layer" | "visual_read" | "both"`.
6. 설명은 한국어로 바꿔 쓴다(paraphrase). 강의 문장을 길게 복사하지 않는다. 지정 전문 용어는 영어 원어를 유지한다.

추가 필드(스키마 버전을 2로 올린다):

```json
"definition": {
  "text_ko": "...", "status": "stated | partial | figure_only | missing",
  "evidence": "text_layer | visual_read | both",
  "sources": [{"file": "NLP/...", "page": 5}, {"file": "NLP/...", "page": 12}],
  "alternatives": [{"text_ko": "...", "sources": [{"file": "NLP/...", "page": 20}]}]
}
```

## 작업 C. coverage_depth 재산정

"facet을 채웠는가"가 아니라 **강의에서 실제로 다룬 정도**로 정한다.

1. 각 개념에 `coverage_stats`를 추가한다:
   `{"files": <실질 설명이 있는 파일 수>, "pages_substantive": <정의·원리·수식·예시·도식으로 다룬 페이지 수>, "pages_mention": <단순 언급 페이지 수>}`
   - "실질 설명"은 해당 페이지가 그 개념을 설명하는 경우다. 단어가 한 번 등장한 것만으로는 세지 않는다.
   - 동음이의어 오탐(예: 일반 영어 단어와 같은 표기)을 걸러낸다.
2. 규칙:
   - `core`: `pages_substantive >= 3` 또는 `files >= 2`
   - `supporting`: `pages_substantive`가 1~2
   - `mention_only`: 실질 설명 없이 언급만 있음
3. 규칙을 적용한 뒤에도 직관과 어긋나는 사례는 `open_issues`에 남긴다(규칙을 임의로 바꾸지 않는다).

## 작업 D. 누락 개념 추가

- 배경 5번의 후보가 강의에 실제로 있는지 확인하고, 있으면 개념으로 추가한다.
  강의에서 확인되지 않으면 추가하지 않고 이유를 기록한다.
- 작업 A에서 새로 읽은 페이지의 개념도 추가한다.
- 기존 개념과 겹치면 새로 만들지 말고 alias나 하위 개념(`parent_id`)으로 정리한다.

## 작업 E. 기타 수정

- `created_by`에 정확한 모델명과 reasoning 설정을 기록한다(사용자에게 확인한 값).
- 기존 `idf.definition`처럼 페이지 텍스트가 정의의 일부만 담은 경우 `partial`로 고친다.

## 산출물

- `data_private/knowledge/concept_map.json` (schema_version 2), 백업 `concept_map.p2b.json`
- `data_private/knowledge/concept_map_checks.json` 갱신:
  - `zero_facet_files`: facet 근거가 하나도 없는 파일(목표는 0개, 남으면 이유를 기록)
  - `visual_read_summary`: 판독 페이지 수, confidence 분포, 읽지 못한 페이지
  - `added_concepts`, `rejected_candidates`(이유 포함)
  - `open_issues`
- `data_private/knowledge/review_sample_p2c.json`: 사람 검토용 무작위 표본 20개
  (`stated`/`partial` facet 중 무작위 추출. 시드를 기록하고, 개념, facet, `text_ko`, 근거 페이지를 포함한다)

## 코드, 테스트, 문서

- 페이지 선정, 렌더링, 통계 계산은 `src/ktide/knowledge/` 아래 스크립트로 만든다.
  비공개 내용(강의 문장, 질문 원문, 파일별 판독 결과)을 코드나 테스트에 넣지 않는다.
- `tests/test_concept_map.py`에 검사를 추가한다:
  - schema_version 2 필드 확인
  - core 개념은 definition과, mechanism·purpose 중 하나 이상이 stated 또는 partial이다
    (예외는 `enrichment_needed.needed == true`이고 reason이 있을 때만 허용)
  - `coverage_depth`가 `coverage_stats`와 규칙에 맞는다
  - visual_read 근거의 페이지가 `visual_transcripts.jsonl`에 존재한다
- `docs/progress/P2c_concept_map_completion.md`에 **집계 수치만** 쓴다.
  P2b 대비 변화(개념 수, 영역별 개수, coverage_depth 분포, facet status 분포,
  definition 채움 비율, evidence 종류 분포, 판독 페이지 수, facet 0건 파일 수)를 표로 비교한다.
  파일명, 개념 설명, 질문 원문은 쓰지 않는다.

## 완료 조건

- `uv run pytest -q`, `uv run ruff check src tests` 통과
- 작업 B의 완료 기준을 만족하거나, 미충족 개념이 모두 사유와 함께 기록됨
- 커밋·push 하지 말고, 결과 요약과 `open_issues`, 그리고 사람 검토가 필요한 표본 위치를 보고한 뒤 멈춘다.
