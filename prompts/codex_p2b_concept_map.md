# Codex 작업 지시: P2b 개념 지도(Concept Map) 구축

권장 설정: `gpt-6.2-sol`, reasoning **medium 이상** (정의·원리 정리의 정확도가 중요함)

---

AGENTS.md를 먼저 읽고 모든 규칙(특히 비공개 경계와 연구 무결성)을 따르라.

## 목적

P2에서 만든 `data_private/audit/concepts.json`은 미리 정한 정규식 용어 41개(`TERMS`)가
어느 페이지에 등장하는지만 찾은 것이다. 그래서 강의에 있지만 목록에 없는 개념(예: 불용어,
Precision/Recall, 데이터 누출)이 빠져 있다. 이번 작업은 **강의 내용에서 직접 개념을 추출**하여,
이후 독립 평가셋의 층화 추출과 학습 데이터 생성의 기준이 될 개념 지도를 만드는 것이다.

교수님의 비공개 평가는 수업 전체 범위에서 무작위로 출제된다. 개념 누락이 가장 큰 위험이므로
정밀도보다 **재현율(빠짐없이 찾기)** 을 우선하라.

## 입력

- `data_private/audit/p2_corpus_draft.json`의 페이지 목록(제외 라벨 페이지는 사용하지 않는다)
- `data_private/audit/inventory.json`의 중복·판본 정보
- `NLP/`의 PDF 텍스트 레이어(읽기 전용, 파일을 수정·이동하지 않는다)

## 작업 절차

1. **파일 단위 추출.** 파일마다 텍스트 레이어를 읽고 개념 후보를 추출한다.
   SHA-256이 같은 파일은 한 번만 처리하고, 판본 후보 쌍은 둘 다 처리한 뒤 출처를 합친다.
2. **개념 단위 기준.** "1~2문장으로 답하는 시험 문제 하나의 대상이 될 수 있는 것"을 개념 하나로 본다.
   예: `Smoothing` 아래에 `Laplace (Add-one) Smoothing`을 별도의 하위 개념으로 둔다.
   지나치게 넓은 묶음(예: "NLP 전반")이나 슬라이드 한 장짜리 예시는 개념으로 만들지 않는다.
3. **병합.** 여러 파일·언어·표기에 걸친 같은 개념을 하나로 합치고 모든 출처를 남긴다.
4. **Facet 정리.** 개념마다 아래 facet을 강의 근거로 정리한다.
   - 설명은 한국어로 짧게 **바꿔 쓴다(paraphrase)**. 강의 문장을 길게 복사하지 않는다.
   - 지정 전문 용어(NLP, SFT, Tokenizer, LoRA, Embedding 등)는 영어 원어를 유지한다.
   - 강의 텍스트에서 확인되지 않으면 내용을 채우지 말고 `status`로 표시한다.
     그림·수식에만 있어 텍스트로 확인할 수 없으면 `figure_only`로 둔다. 추측하지 않는다.
   - 외부 지식으로 보충하지 않는다(보강은 다음 단계). 보강이 필요하면 `enrichment_needed`에 표시한다.
5. **재현율 점검.**
   - 기존 `TERMS` 41개가 모두 개념 지도에 대응되는지 확인한다(대응 안 되면 이유를 기록).
   - 교수님 공개 질문 11개(`data_private/professor/TEST_Qwen25_SFT.ipynb`의 `QUESTIONS`)가
     각각 하나 이상의 `concept_id`에 대응되는지 확인한다. 대응되지 않으면 해당 개념이 강의에
     있는지 다시 찾아보고, 정말 없으면 `not_in_lecture`로 기록한다.
     **이 질문들은 누락 점검에만 쓰고 평가셋 문항으로 쓰지 않는다.**
6. **영역 분류.** 각 개념을 아래 영역 중 하나에 배정한다. 맞는 영역이 없으면 `other`와 이유를 쓴다.

| domain | 범위 |
|---|---|
| `D01_preprocessing` | NLP 개요, 정규식, 정규화, 토큰화, 불용어, 어간·표제어, BPE 등 subword |
| `D02_ngram_lm` | N-gram LM, 확률 추정, smoothing, perplexity |
| `D03_classification_eval` | Naive Bayes, Logistic Regression, 평가 지표, 데이터 분할·검증 |
| `D04_neural_training` | 신경망, 활성화, loss, backpropagation, 최적화, 과적합·정규화 |
| `D05_embedding` | TF-IDF, 분포 가설, Word2Vec, 유사도, 문장 임베딩 |
| `D06_sequence_labeling` | POS, NER, BIO 태깅 |
| `D07_attention_transformer` | Attention, Self-attention, Multi-head, 위치 정보, Transformer 구조 |
| `D08_pretrained_models` | 사전학습, MLM, BERT, GPT 계열 |
| `D09_llm_training_use` | SFT, instruction tuning, 정렬, prompting, decoding |
| `D10_efficiency` | LoRA 등 PEFT, 양자화, 경량화, distillation |

## 출력 (모두 `data_private/knowledge/` 아래, UTF-8, `ensure_ascii=False`)

### `concept_map.json`

```json
{
  "schema_version": 1,
  "created_by": {"tool": "codex", "model": "<모델명>", "reasoning": "<설정>"},
  "concepts": [
    {
      "concept_id": "laplace_smoothing",
      "canonical_term": "Laplace Smoothing",
      "ko_name": "라플라스 스무딩",
      "aliases_ko": ["가산 스무딩"],
      "aliases_en": ["Add-one Smoothing"],
      "abbreviations": [],
      "preserve_english": true,
      "domain": "D02_ngram_lm",
      "parent_id": "smoothing",
      "related_ids": ["perplexity"],
      "coverage_depth": "core | supporting | mention_only",
      "facets": {
        "definition":  {"text_ko": "...", "status": "stated | partial | figure_only | missing", "sources": [{"file": "NLP/...", "page": 12}]},
        "mechanism":   {"text_ko": null, "status": "missing", "sources": []},
        "purpose":     {...},
        "advantages":  {...},
        "limitations": {...},
        "formula":     {...}
      },
      "lecture_sources": [{"file": "NLP/...", "page": 12, "role": "definition | mechanism | example | formula | figure | mention"}],
      "enrichment_needed": {"needed": true, "reason": "..."},
      "notes": ""
    }
  ]
}
```

위 예시의 값은 형식 설명용이다. 실제 강의 내용으로 채워라.

### `concept_map_checks.json`

- `terms_mapping`: 기존 TERMS 41개 → concept_id (또는 미대응 사유)
- `public_question_coverage`: 공개 질문 번호 → concept_id 목록 또는 `not_in_lecture`
- `files_processed`: 처리한 파일, 건너뛴 파일과 이유
- `open_issues`: 판단이 필요한 사항(사람 검토용)

## 코드와 문서

- 재사용 가능한 스크립트는 `src/ktide/knowledge/`에 둔다. 비공개 내용(강의 문장, 질문 원문)을
  코드나 테스트에 넣지 않는다. 경로와 스키마만 다룬다.
- P2의 `data_private/audit/run_inventory.py`, `make_review_sheets.py`에 비공개 내용이 없으면
  `src/ktide/audit/`로 옮겨 재현 가능하게 한다(내용이 있으면 옮기지 말고 보고한다).
- `concept_map.json`의 스키마 검증 테스트를 `tests/`에 추가한다
  (필수 필드, domain 값, 모든 source의 file이 `NLP/`의 PDF이고 page가 범위 안인지, concept_id 중복 없음,
  parent_id/related_ids가 존재하는 ID인지).
- 공개 요약은 `docs/progress/P2b_concept_map.md`에 **집계 수치만** 쓴다:
  개념 수, 영역별 개수, coverage_depth 분포, facet status 분포, enrichment_needed 개수,
  TERMS 대응률, 공개 질문 대응 여부 개수. 개념 설명이나 질문 원문은 쓰지 않는다.

## 완료 조건

- `uv run pytest -q`, `uv run ruff check src tests` 통과
- 공개 질문 11개 모두 대응 또는 `not_in_lecture`로 판정됨
- 커밋·push 하지 말고, 결과 요약과 `open_issues`를 보고한 뒤 멈춘다.
