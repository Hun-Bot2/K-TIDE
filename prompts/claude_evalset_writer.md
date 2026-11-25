# Claude 작업 지시: 평가셋 문항 초안 작성

작성자: Claude. 학습 QA는 Codex가 쓰므로, 평가 문항은 반드시 Claude가 쓴다(생성 모델 분리).
AGENTS.md의 비공개 경계와 `docs/research/evaluation_protocol.md`를 따른다. 모든 입력과 출력은 `data_private/` 안에서만 다룬다.

## 입력

- `data_private/evalset/plan_v1.json`: 채워야 할 슬롯(`slot_id, split, concept_id, domain, question_type, term_form, variant_group`)
- `data_private/knowledge/cku_v2.jsonl`: 개념별 핵심 지식(정답의 근거). `cku_v2_1.jsonl`이 있으면 그것을 쓴다.
- `data_private/knowledge/concept_map.json`: 용어 표기(`canonical_term`, `ko_name`, `aliases_*`, `abbreviations`)와 강의 근거
- `data_private/knowledge/lecture_pages.json`: 강의 페이지 텍스트(파일명 비교 시 NFC 정규화)

**읽지 않는다:** `data_private/professor/`, `data_private/colab_outputs/`, `runs/`, 교수님 노트북.
평가셋은 교수님 질문과 독립이어야 한다.

## 문항 스타일

짧고 직접적인 한국어 질문. 대부분 한 문장, 보통 30자 안팎. 시험에서 한두 문장으로 답할 수 있어야 한다.

| question_type | 질문 형태 예 | 정답이 담아야 할 것 |
|---|---|---|
| `definition` | "X란 무엇인가?", "X는 무엇을 하는가?" | 정의의 핵심 |
| `purpose` | "X를 사용하는 이유는?", "X의 역할은?" | 해결하는 문제·목적 |
| `mechanism` | "X는 어떻게 동작하는가?", "X는 무엇을 계산하는가?" | 동작 원리·계산 |
| `comparison` | "X와 Y의 차이는?" (Y는 CKU `contrast_with`에서) | 핵심 차이 한두 가지 |
| `limitation` | "X의 한계 한 가지는?" | 한계와 그 이유 |
| `consequence` | "~하면 어떤 문제가 생기는가?", "X가 없으면 어떻게 되는가?" | 결과와 원인 |
| `judgment` | "X는 항상 좋은가?", "X만 쓰면 충분한가?" | 판단(대개 "아니다/상황에 따라")과 근거 |
| `calculation` | 작은 수치를 주고 값을 묻는다(예: 확률·빈도·지표·파라미터 수) | 최종 값과 핵심 계산식 한 줄. 30어절 안에서 검산 가능하게 |

- `calculation` 문항은 질문에 필요한 수치를 모두 주고, 정답이 하나로 정해지게 한다. 소수는 반올림 자릿수를 질문에 명시한다.
  정답은 직접 계산해 두 번 검산한다(Python으로 확인). 강의의 공식과 표기를 따른다.

- 질문 안에 정답을 드러내지 않는다(정의를 질문에 넣고 이름을 묻는 식 금지).
- 강의 문장을 그대로 옮긴 질문을 만들지 않는다. 같은 개념이라도 다른 슬롯의 질문과 표현을 다르게 쓴다.
- 질문은 하나의 답으로 수렴해야 한다(모호하면 조건을 덧붙인다).

## 용어 표기(term_form)

| term_form | 질문에서의 표기 |
|---|---|
| `ko` | 한국어 이름만(`ko_name`). 영어 단어를 쓰지 않는다 |
| `en` | 영어 원어(`canonical_term` 또는 영어 별칭)에 한국어 조사 |
| `abbr` | 약어만(예: SFT, BPE) |
| `mixed` | 한국어와 영어를 함께(예: 한국어 이름 뒤 괄호에 영어, 또는 영어 용어와 한국어 설명) |

- `variant_group`이 같은 슬롯은 **같은 의도의 질문**을 표기만 바꿔 쓴다. 그 외 단어는 최대한 같게 둔다.
- 조사는 영어 용어를 한국어로 읽은 마지막 소리로 고른다(받침 있으면 은/이/을, 없으면 는/가/를).

## 정답(reference_answer_ko)

- **한국어 1~2문장, 공백 기준 30어절 이내.** 질문에 직접 답하고 핵심 이유를 포함한다. 서론·인사 없음.
- 근거는 CKU(`core_answer_ko`, `definition_ko`, `mechanism_ko`, `purpose_ko`, `limitations_ko`, `contrast_with`,
  `misconceptions_ko`)와 강의 페이지. CKU가 강의와 다르게 기록한 부분(`lecture_alignment`)은 강의 정의를 우선한다.
- 지정 전문 용어(NLP, SFT, Tokenizer, LoRA, Embedding, Transformer, Attention 등 `preserve_english: true`)는 영어 원어로 쓴다.
- `key_points_ko`: 채점 시 정답에 반드시 있어야 할 핵심 요소 1~3개(짧은 구).
- `required_terms`: 답에서 영어 원어로 남아야 할 용어 목록(없으면 빈 목록).

## 출력

`data_private/evalset/draft/<group>.jsonl`, 슬롯당 한 줄:

```json
{"item_id": "<slot_id와 같게>", "slot_id": "...", "split": "...", "concept_id": "...", "domain": "...",
 "question_type": "...", "term_form": "...", "variant_group": null,
 "question_ko": "...", "reference_answer_ko": "...", "key_points_ko": ["..."], "required_terms": ["..."],
 "lecture_sources": [{"file": "NLP/...", "page": 3}],
 "writer": {"tool": "claude", "model": "claude-opus-5-5", "prompt": "prompts/claude_evalset_writer.md"},
 "status": "draft", "writer_notes": "확신이 낮거나 사람 확인이 필요한 점(없으면 빈 문자열)"}
```

- 슬롯의 `split, concept_id, question_type, term_form, variant_group`은 바꾸지 않는다.
  CKU에 내용이 없어 그 유형으로 쓸 수 없으면 가장 가까운 유형으로 쓰지 말고, 슬롯 값을 유지한 채 `writer_notes`에 이유를 쓴다.
- 작성 후 `uv run python -I`로 각 정답의 어절 수(`ktide.metrics.word_count`)와 문장 수를 확인한다.
- `data_private/evalset/draft/` 밖에는 아무것도 쓰지 않고, 기존 파일을 수정하지 않으며, 커밋하지 않는다.
