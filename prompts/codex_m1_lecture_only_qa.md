# Codex 작업 지시: M1 학습 데이터 — 강의 자료만으로 QA 생성

권장 설정: `gpt-6.2-sol`, reasoning **high**. 이 작업은 P2g(CKU v3 교재 보강)와 **동시에** 진행될 수 있다.
P2g가 쓰는 파일(`data_private/knowledge/cku_v3*`, `data_private/external/slp/`, `src/ktide/knowledge/`)은 건드리지 않는다.

---

AGENTS.md를 먼저 읽고 따르라(비공개 경계, 연구 무결성, 출처 분리).

## 목적

2×2 통제 실험의 첫 학습 조건 **M1(Lecture-only)** 과 **M2(Lecture-only + 용어 보존)** 의 학습 데이터를 만든다.
이 데이터는 **강의 자료에 근거가 있는 내용만** 담아야 한다. 이후 지식 보강 조건(M3, M4)과 비교해
"강의 자료만으로 어디까지 오르는가"를 측정한다.

## 근거로 쓸 수 있는 것 (이것만)

- 강의 페이지 텍스트: `data_private/knowledge/lecture_pages.json` 중 `data_private/audit/corpus_v2.json`에 있는 페이지
- 강의 이미지 판독: `data_private/extracted/visual_terms.jsonl`, `data_private/extracted/visual_transcripts.jsonl`
- 개념 지도의 강의 근거 층: `data_private/knowledge/concept_map.json`의 `facets`, `lecture_sources`
- 표기 규칙: `data_private/knowledge/review/particle_rules.json`

## 쓰면 안 되는 것

- **CKU(`cku_v*.jsonl`)의 Teacher 작성 내용**, 교재(`Speech-Language/`, `data_private/external/`), 외부 자료, 모델 자신의 지식으로 내용을 보충하는 것.
  강의에 근거가 없으면 그 문항을 만들지 않는다. (문장을 매끄럽게 바꿔 쓰는 것은 허용)
- **평가셋**: `data_private/evalset/` 전체를 읽지 않는다.
- **교수님 질문**: `data_private/professor/`, `data_private/colab_outputs/`, 강의 자료 안의 "기말과제 평가 데이터 예시" 페이지
  (`2026-NLP-LLM 모델 경량화.pdf` 9·11·12쪽)를 근거로 쓰지 않는다.
- **unseen 개념**: `data_private/evalset/plan_v1.json`의 `unseen_concepts` 25개는 데이터에 넣지 않는다.
  (이 파일에서 `unseen_concepts` 목록만 읽는다. 다른 필드는 읽지 않는다.)

## 생성 규칙

1. 개념별로 강의 근거 페이지를 읽고, 근거가 허용하는 만큼 QA를 만든다. 개념당 **최대 8개**, 근거가 얇으면 더 적게(0개도 가능).
2. 질문 유형을 섞는다: 정의, 목적·이유, 원리, 비교, 한계, 결과(~하면 어떤 문제가?), 판단(항상 그런가?), 계산(강의에 공식·예시가 있을 때만).
3. 질문 표기를 섞는다: 한국어 용어, 영어 용어, 약어, 혼합. 같은 개념의 질문끼리 표현이 겹치지 않게 한다.
4. 답변: **한국어 1~2문장, 공백 기준 30어절 이내**, 질문에 바로 답하고 핵심 이유를 포함한다. 서론·인사 없음.
5. **두 가지 답변 버전을 같은 QA에 함께 쓴다**(용어 정책만 다르고 내용은 같아야 한다):
   - `answer_translated_ko` (M1): 전문 용어를 영어 알파벳 대신 **한국어로** 쓴다. 널리 쓰이는 번역어가 있으면 번역어
     (예: Precision→정밀도, Recall→재현율), 없으면 한글 음차(예: Embedding→임베딩, Attention→어텐션).
     약어는 한국어 풀이로 쓴다(예: SFT→지도 미세조정). 정해진 번역어는 `data_private/train/m1_lecture_only/term_translations.json`에
     용어별로 기록하고 모든 QA에서 같은 번역어를 쓴다.
   - `answer_preserved_ko` (M2): 지정 전문 용어(NLP, SFT, Tokenizer, LoRA, Embedding, Transformer, Attention, 혼동 행렬 용어 등
     `preserve_english: true`)를 영어 원어로 유지한다. 조사는 `particle_rules.json`을 따른다.
   - 두 버전은 용어 표기 외에 단어·문장 구조를 최대한 같게 둔다.
6. 각 QA에 근거 페이지를 1개 이상 붙인다. 근거 페이지에서 확인되지 않는 내용을 답에 넣지 않는다.

## 출력

`data_private/train/m1_lecture_only/qa.jsonl`, QA당 한 줄:

```json
{"qa_id": "m1-00001", "concept_id": "...", "domain": "...", "question_type": "...", "question_form": "ko | en | abbr | mixed",
 "question_ko": "...", "answer_translated_ko": "...", "answer_preserved_ko": "...",
 "evidence": [{"file": "NLP/...", "page": 5, "source": "text_layer | visual_read"}],
 "basis": "lecture", "generator": {"tool": "codex", "model": "<정확한 모델명>", "reasoning": "high",
 "prompt": "prompts/codex_m1_lecture_only_qa.md"}}
```

`data_private/train/m1_lecture_only/coverage.json`: 개념별 생성 수, 근거 부족으로 만들지 못한 개념과 사유.

## 품질 점검 (스크립트로 자동 확인)

`src/ktide/train_data/` 아래에 점검 스크립트를 만들고 결과를 `data_private/train/m1_lecture_only/qc.json`에 쓴다.

- 두 답변 모두 30어절 이내 1~2문장(`ktide.metrics`)
- `answer_preserved_ko`의 지정 용어 영어 유지, 조사 규칙 일치
- 두 답변 버전의 차이가 용어 표기뿐인지(용어를 같은 표지로 바꾼 뒤 문자 유사도 0.85 이상)
- 근거 페이지가 `corpus_v2`에 있고, 금지 페이지(과제 예시 페이지)가 아님
- unseen 개념 없음
- 완전 중복·근접 중복 질문 제거(문자 n-gram 유사도 0.8 이상)
- 개념별·유형별·표기별 분포

## 코드와 문서

- 비공개 내용(강의 문장, 질문·답변 원문)을 코드나 테스트에 넣지 않는다.
- `tests/`에 형식 검사를 추가한다(필수 필드, 금지 페이지·unseen 개념 없음, 길이 제한).
- `docs/progress/M1_lecture_only_data.md`에 **집계 수치만** 쓴다: QA 수, 데이터가 있는 개념 수와 없는 개념 수,
  유형·표기·영역 분포, 평균 어절 수, 점검 실패 건수.

## 완료 조건

- `uv run pytest -q`, `uv run ruff check src tests` 통과
- 커밋·push 하지 말고 결과 요약과 근거 부족 개념 목록을 보고한 뒤 멈춘다. 이후 Claude가 표본을 검증하고 평가셋과의 중복을 점검한다.
