# Codex 작업 지시: P2d-0 중복 정리와 추출 대상 선별

권장 설정: `gpt-6.2-sol`, reasoning **medium**, 텍스트가 적은 페이지와 이미지 확인에 이미지 입력 사용.

---

AGENTS.md를 먼저 읽고 모든 규칙(특히 비공개 경계와 연구 무결성)을 따르라.

이 작업은 이미지 정밀 판독(P2d) **전에** 코퍼스를 정리하여, 판독·라벨링할 대상을 "개념 지식을 담은 고유한 내용"으로 줄이는 단계다.
강의 자료에는 다음과 같은 중복과 불필요한 내용이 많다.

- **파일 사이의 중복:** 같은 강의의 사본, 판본, 다른 강의에 재사용된 슬라이드
- **파일 안의 중복:** 애니메이션 단계별로 저장된 슬라이드(같은 슬라이드에 내용이 한 줄씩 추가됨),
  앞에서 나온 슬라이드를 다시 보여 주는 요약·복습 슬라이드, 같은 도식을 여러 페이지에 반복 사용
- **이미지 중복:** 같은 그림·도식이 여러 페이지와 파일에 반복해서 들어 있음
- **추출할 필요가 없는 내용:** 페이지 전체 또는 페이지 안 일부 요소가 개념 지식과 무관함

원본 PDF는 삭제하거나 이동하지 않는다. 모든 제외는 **페이지 단위·요소 단위 라벨**로만 기록하며, 언제든 되돌릴 수 있어야 한다.
판단이 애매하면 남긴다(재현율 우선). 사용자가 이미 내린 라벨(`page_labels.json`)은 바꾸지 않는다.

## 입력

- `data_private/audit/inventory.json`: 파일별 SHA-256, 페이지 수, 완전 중복, 판본 후보
- `data_private/audit/p2_corpus_draft.json`: 현재 후보 코퍼스(1,490쪽)
- `data_private/audit/page_labels.json`: 사용자 라벨
- `data_private/knowledge/lecture_pages.json`, `data_private/extracted/visual_transcripts.jsonl`: 페이지 텍스트
- `NLP/`의 PDF(읽기 전용)

## 작업 A. 파일 사이의 중복 정리

1. 후보 코퍼스의 모든 페이지 쌍에 대해 유사도를 계산한다.
   - 텍스트가 충분한 페이지: 정규화한 텍스트의 문자 n-gram 유사도(예: MinHash/Jaccard)
   - 텍스트가 적은 페이지: 렌더링 이미지의 지각 해시(pHash 등) 거리
   기준과 임계값을 코드와 문서에 기록한다.
2. `version_candidates`의 파일 쌍과 새로 발견한 겹치는 파일 쌍마다 관계를 분류한다:
   `identical | superset | revised | partial_overlap | unrelated`. 페이지 대응(정렬) 결과도 기록한다.
3. 거의 같은 페이지 묶음마다 대표 페이지 하나를 남기고, 나머지는 `duplicate_of`로 표시한다.
   - 대표 선택 순서: 내용이 더 완전한 쪽 → PDF 메타데이터 수정일이 더 최근인 쪽 → 파일의 페이지 수가 더 많은 쪽
   - 설명이 일부라도 다르면(수정되거나 추가된 설명) 둘 다 남긴다.

## 작업 B. 파일 안의 중복 정리

1. **애니메이션 단계 슬라이드.** 같은 파일에서 연속된 페이지 중 앞 페이지의 내용(텍스트와 시각 요소)이
   뒤 페이지에 모두 포함되면 빌드 단계로 본다. 가장 완성된 마지막 페이지만 남기고, 앞 페이지는
   `build_step_of`로 표시한다. 텍스트 포함 관계와 이미지 차이(추가된 영역만 다름)를 함께 확인한다.
2. **반복·복습 슬라이드.** 같은 파일 안에서 앞서 나온 슬라이드를 다시 보여 주는 페이지(요약, 복습, 재등장)는
   `duplicate_of`로 표시한다. 단, 요약 슬라이드가 여러 개념을 새로 연결하거나 비교하는 설명을 추가했다면 남긴다.

## 작업 C. 이미지 중복 정리

1. PDF에 들어 있는 이미지(`pdfimages` 등으로 추출)와, 벡터 도식이 있는 페이지 영역을 해시로 식별한다.
2. 같은 그림이 여러 페이지·파일에 나오면 하나의 `figure_id`로 묶는다.
   P2d에서는 **`figure_id`마다 한 번만 판독**하고, 나머지 페이지는 그 판독 결과를 참조한다.
3. 결과를 `data_private/extracted/figure_index.json`에 저장한다:
   `{"figure_id": "...", "hash": "...", "occurrences": [{"file": ..., "page": ..., "bbox": [x0, y0, x1, y1]}], "representative": {"file": ..., "page": ...}, "extract": true}`

## 작업 D. 추출할 필요가 없는 내용 제외

### 페이지 단위 제외

아래 범주의 페이지는 `exclude`로 표시한다. **개념 설명이 조금이라도 있으면 남긴다.**

| 범주 | 예시 |
|---|---|
| `cover` | 표지, 강의 제목만 있는 페이지 |
| `toc` | 목차, 오늘의 순서(agenda), 학습 목표 나열만 있는 페이지 |
| `divider` | 장·절 구분 슬라이드(제목만 있음) |
| `references` | 참고문헌, 출처·URL 목록, 크레딧, 저작권 표시 |
| `logistics` | 수업 운영, 일정, 과제·평가·제출 안내 |
| `closing` | 감사, Q&A, 빈 페이지 |
| `decorative` | 장식 이미지만 있는 페이지 |
| `setup_only` | 설치, 환경 설정, 계정·API 키 발급 안내 |
| `code_only` | 개념 설명 없이 코드, 실행 로그, 출력 결과만 있는 페이지 |
| `data_dump` | 데이터셋 샘플·표·말뭉치 예문을 나열만 한 페이지 |
| `news_or_promo` | 제품 소개, 뉴스·기사 캡처, 기업·모델 홍보, 인물 소개 |

- `code_only`와 `data_dump`는 신중하게 판단한다. 코드나 예시가 개념을 보여 주면(예: 설정값의 의미, 수식의 구현,
  토큰화 결과로 BPE 동작을 설명) 남긴다.
- 먼저 규칙(텍스트 길이, 키워드, 페이지 위치)으로 후보를 고르고, 텍스트가 적은 후보는 **썸네일로 직접 확인**한다.
  여러 페이지를 한 장에 모은 contact sheet를 쓰면 빠르다.

### 요소 단위 제외(페이지는 남기되 판독하지 않을 부분)

페이지에 개념 설명이 있더라도 아래 요소는 P2d에서 판독하지 않도록 `skip_regions`에 표시한다.

- 로고, 장식 아이콘, 인물 사진, 배경 이미지
- 논문·웹페이지·제품 화면의 캡처 중 개념 설명이 없는 부분
- 페이지 머리글·바닥글, 슬라이드 번호, 출처 표기
- 이미 `figure_index`에서 대표 판독이 지정된 반복 그림(참조로 대체)

## 작업 E. 사람 검토

- 판단이 애매한 페이지(유사도가 임계값 근처, 빌드 단계 판정, `code_only`, `data_dump`, `news_or_promo`,
  개념 설명이 짧게 섞인 `toc`·`cover`)를 `data_private/audit/human_review_queue.json`에 추가한다.
  기존 항목 형식을 따르고, 질문을 구체적으로 쓴다.
- 범주마다 제외한 페이지 중 무작위 5쪽씩(시드 기록)을 `data_private/audit/exclusion_audit_sample.json`에 남겨,
  사용자가 잘못 제외된 페이지가 없는지 확인할 수 있게 한다.
- 기존 라벨링 도구(`src/ktide/label_pages.py`)로 사용자가 검토할 수 있어야 한다. 필요하면 도구를 확장하되,
  비공개 내용을 코드에 넣지 않는다.
- 사용자 검토가 끝나기 전에는 애매한 페이지를 `keep`으로 둔다.

## 산출물

- `data_private/audit/page_filter.jsonl`: 후보 코퍼스의 모든 페이지에 한 줄씩
  ```json
  {"source": {"file": "NLP/...", "page": 3}, "sha256": "...",
   "decision": "keep | exclude",
   "reason": "duplicate | build_step | repeated_slide | cover | toc | divider | references | logistics | closing | decorative | setup_only | code_only | data_dump | news_or_promo | null",
   "duplicate_of": {"file": "NLP/...", "page": 5} | null,
   "similarity": 0.97, "method": "text | image | manual",
   "skip_regions": [{"bbox": [x0, y0, x1, y1], "reason": "logo | photo | screenshot | header_footer | repeated_figure", "figure_id": null}],
   "needs_human_review": false}
  ```
- `data_private/audit/version_relations.json`: 파일 쌍별 관계 분류와 페이지 정렬
- `data_private/extracted/figure_index.json`: 반복 그림 색인
- `data_private/audit/corpus_v2.json`: `keep` 페이지 목록(이후 P2d의 입력)
- `data_private/extracted/visual_queue_v2.json`: `corpus_v2` 기준 시각 판독 대상(반복 그림은 대표만 포함, `skip_regions` 반영)
- `data_private/audit/exclusion_audit_sample.json`
- 기존 `p2_corpus_draft.json`과 `visual_queue.json`은 덮어쓰지 않는다.

## 코드, 테스트, 문서

- 유사도 계산, 빌드 단계 판정, 이미지 해시, 규칙 분류는 `src/ktide/audit/` 아래 스크립트로 만든다.
  비공개 내용(강의 문장, 파일명)을 코드나 테스트에 넣지 않는다.
- `tests/`에 검사를 추가한다:
  - `page_filter.jsonl`이 후보 코퍼스의 모든 페이지를 정확히 한 번씩 포함함
  - `duplicate_of`·`build_step_of`가 가리키는 페이지는 `keep`이고, 연쇄(중복의 중복)가 없음
  - 사용자 라벨과 충돌하는 결정이 없음
  - `corpus_v2.json`이 `keep` 페이지와 일치함
  - `figure_index`의 대표 페이지는 모두 `keep`이며, `visual_queue_v2`에 반복 그림의 대표가 아닌 사본이 없음
- `docs/progress/P2d0_dedupe_filter.md`에 **집계 수치만** 쓴다:
  - 판본 관계별 파일 쌍 수
  - 제외 사유별 페이지 수(파일 간 중복, 빌드 단계, 반복 슬라이드, 각 무의미 범주)
  - 반복 그림 묶음 수와 중복 등장 횟수
  - 요소 단위 제외 개수(사유별)
  - 사람 검토 대기 수
  - 코퍼스 크기 변화(1,490 → ?), 시각 판독 대상 변화(480 → ?)
  - 파일명과 페이지 내용은 쓰지 않는다.

## 완료 조건

- 후보 코퍼스 전체 페이지에 결정이 있음
- `uv run pytest -q`, `uv run ruff check src tests` 통과
- 커밋·push 하지 말고, 결과 요약, 사람 검토 대기 목록, 제외 표본 위치를 보고한 뒤 멈춘다.
  **P2d(이미지 정밀 판독)는 사용자 검토가 끝난 뒤에 시작한다.**
