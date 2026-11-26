# AGENTS.md — K-TIDE 작업 규칙

이 파일은 이 저장소에서 일하는 모든 코딩 에이전트(Codex, Claude Code 등)가 따르는 규칙이다.
규칙이 사용자 지시와 충돌하면 작업을 멈추고 사용자에게 확인한다.

## 1. 프로젝트 요약

- 목표 1: 교수님 비공개 평가(수업 전체 범위에서 무작위로 출제되는 한국어 NLP/ML 질문)에서
  `Qwen/Qwen2.5-1.5B-Instruct` SFT 모델의 성능을 높인다.
- 목표 2: 성능 개선 방법을 정량적으로 검증하여 ACL 형식 논문으로 작성한다.
- K-TIDE는 모델 구조가 아니라 데이터 구축 및 Fine-tuning 방법론의 이름이다.
- 답변 조건: 한국어, 1~2문장, 공백 기준 30어절 이내, 최종 답만 출력.
  NLP, SFT, Tokenizer, LoRA, Embedding 등 지정된 전문 용어는 영어 원어를 유지한다.

## 2. 현재 단계

- 완료: P0 저장소 초기화, P1 B0 Baseline (`docs/progress/P1_baseline_B0.md`),
  P2 강의 자료 분석(P2·P2b·P2c·P2d-0, `docs/progress/P2*.md`).
- 진행 중: **P2e 핵심 개념 정리(CKU)** — Codex가 작성하고 Claude가 검증한다
  (`prompts/codex_p2e_canonical_knowledge.md`, `prompts/claude_cku_review.md`).
- 다음: 독립 평가셋 구축 → 확장 Baseline.
- 아직 하지 않는다: 모델 학습, 외부 데이터 대량 다운로드, 합성 QA 대량 생성.
  단계를 넘어가기 전에는 사용자의 검토와 승인을 받는다.

### 두 개의 문서 트랙

- **트랙 A — 과제 보고서** (`report_course/`, gitignore): 교수님께 제출. 과제 조건, 교수님 노트북, 공개 질문 결과를 다룰 수 있다.
- **트랙 B — 학회 논문** (`paper/`, 공개): NAACL 2027 SRW. **과제·채점·교수님 평가를 언급하지 않는다.** 집계 수치만 쓴다.
- 두 트랙의 내용을 섞지 않는다. 트랙 A 내용을 `paper/`나 공개 문서에 옮기지 않는다.
- 상세: `docs/research/goals_and_timeline.md`

## 3. 비공개 경계 (가장 중요)

이 저장소는 **공개(PUBLIC) GitHub 저장소**다. 다음은 절대 커밋하거나 외부에 공개하지 않는다.

| 비공개 대상 | 위치 |
|---|---|
| 교수님 강의 PDF 및 노트북 | `NLP/` (읽기 전용) |
| 공식 교재 SLP 일부 장(All rights reserved) | `Speech-Language/` (읽기 전용, `_excluded/`는 범위 밖이므로 사용 금지) |
| 교재에서 파생한 텍스트·근거 | `data_private/external/slp/` |
| 교수님 평가 노트북 원본 | `data_private/professor/TEST_Qwen25_SFT.ipynb`, 루트의 `TEST_Qwen25_SFT.ipynb` |
| 교수님 공개 질문 11개, 모델 답변, Judge 결과 | `runs/`, `data_private/colab_outputs/` |
| 강의에서 추출한 텍스트·이미지·용어집·QA 등 모든 파생 데이터 | `data_private/` 아래에만 저장 |
| 모델 가중치, 제출 ZIP | `*.safetensors`, `*.zip`, `checkpoints/`, `submission/` |
| API 키 | `.env` |

규칙:

- 강의 자료에서 파생된 산출물은 **반드시 `data_private/` 아래**에 저장한다
  (예: `data_private/extracted/`, `data_private/audit/`). 그 밖의 경로에 쓰지 않는다.
- 공개 가능한 것은 코드, 설정, 연구 문서, **집계된 수치**뿐이다. 문서와 코드, 테스트에
  교수님 질문 원문, 강의 원문 문장, 모델 답변 원문을 넣지 않는다.
- **예외(2026-11-26 사용자 결정):** Colab 실행용 번들과 그 결과(`data_private/colab/`, 학습 결과 ZIP)는
  Hugging Face dataset repo `HunBot/K-TIDE-Dataset`(사용자 결정으로 **공개**)에 올린다.
  공개 범위는 사용자가 관리한다. GitHub 저장소에는 여전히 커밋하지 않는다.
- **예외(과제 요건):** 최종 과제 모델 ZIP은 테스트 노트북의 `MODEL_ZIP_URL`로 받을 수 있도록 공개 다운로드 위치
  (Hugging Face 공개 repo)에 올린다. 가중치는 여전히 GitHub에 커밋하지 않는다.
- `.gitignore`를 약화하지 않는다. `git add -A` 전에 `git status --short`로 확인한다.
- `git push`, 공개 저장소 생성, 공개 링크 생성은 사용자가 명시적으로 요청할 때만 한다.
- 커밋 전 `uv run pytest -q`를 실행한다. `tests/test_privacy.py`가 비공개 파일 추적을 막는다.

## 4. 연구 무결성

- 실행하지 않은 결과, 수치, 그래프를 만들어 내지 않는다. 가설을 사실처럼 쓰지 않는다.
- 생성된 답변을 수정하거나 요약하지 않는다. 30어절을 넘거나 실패한 답변도 지우지 않고 기록한다.
- `runs/` 아래의 기존 실행 결과를 덮어쓰지 않는다(새 run 디렉터리를 만든다).
- 논문 인용은 원문을 직접 확인한 것만 사용한다. 확인하지 않은 항목은 미검증으로 표시한다.
- PDF의 이미지, 수식, 다이어그램에서 확인되지 않은 내용을 추측해서 지식으로 저장하지 않는다.
- **이미지 판독(시각 분석)은 작업 지시문이 요청한 경우에 허용한다**(예: P2d, P2e 작업 1).
  이때 페이지 이미지를 직접 보고 **보이는 것만** 기록하며, 판독 결과에는 `method: "visual_read"`와
  신뢰도를 남긴다. 읽을 수 없는 부분은 추측하지 말고 읽지 못한 이유를 기록한다.
  작업 지시문이 이미지 판독을 요청하지 않았다면 텍스트 추출이 불충분한 페이지는 "시각 분석 필요"로 표시만 한다.
- 대형 모델(Teacher)이 작성한 지식은 강의 근거와 섞지 않고 `provenance: "llm_teacher"`로 분리해 저장한다.
  외부 자료는 실제로 열어 본 것만 출처로 적는다.

## 5. 교수님 평가 노트북 규칙

- 교수님 노트북은 수정하지 않는다. 입력은 `MODEL_ZIP_URL`만 허용된다.
- 제출 모델은 원본 Qwen의 Tokenizer, Chat Template, Special Tokens를 유지한다.
  Chat Template이나 Tokenizer 설정으로 System Prompt, Glossary, 예시 답변을 삽입하지 않는다.
- **ADR-0001:** `generation_config.json`은 원본 파일을 바이트 그대로 복사해서 제출한다.
  `save_pretrained`가 `transformers_version`을 4.57.1로 바꾸면 교수님 노트북의 greedy
  decoding이 sampling으로 바뀐다(`docs/decisions/0001-*.md`).
- 양자화하지 않는다. 최종 제출은 비양자화 Full Model safetensors ZIP이다.

## 6. P2 강의 자료 분석 가이드

입력: `NLP/` 의 PDF(읽기 전용). 원본 파일을 이동하거나 수정하지 않는다.

조사 항목:

- 파일별 주제, 페이지 수, 언어(한국어/영어/혼합), 추출 가능한 텍스트 비율
- 중복 파일: 완전히 같은 파일(해시 기준)과 같은 강의의 다른 버전(예: `(1)` 사본,
  `Tokenization` 계열, `Transformer` 계열)을 구분한다.
- 페이지 유형: 텍스트 중심 / 수식·표 / 정보성 이미지·다이어그램 / 장식용 / 표지·목차
- 핵심 개념 목록. 여러 파일에 겹치는 개념은 하나로 통합하고 출처를 모두 남긴다.
- 불완전한 정의, 누락된 원리, 이미지에만 있는 설명(외부 자료 보강 후보)

산출물 규칙:

- 모든 항목에 출처를 `{"file": ..., "page": ...}` 형태로 남긴다(페이지는 1부터 센다).
- 기계가 읽는 결과는 `data_private/audit/` 아래 JSON 또는 JSONL(UTF-8, `ensure_ascii=False`)로 저장한다.
- 공개 가능한 요약(파일 수, 페이지 수, 페이지 유형 비율 같은 집계 수치만)은
  `docs/progress/P2_lecture_audit.md`에 쓴다.
- 평가셋은 이 분석을 바탕으로 개념을 분류한 뒤 Stratified Sampling으로 만든다(P2 이후 단계).

## 7. 개발 환경과 명령어

- Python 3.12, `uv`. 의존성 추가는 현재 단계에 필요한 최소한으로 하고 `uv add`를 쓴다.
- 교수님 노트북과 버전을 맞춘 패키지(`transformers==4.57.1` 등)는 바꾸지 않는다.

```bash
uv sync                                   # 환경 구성
uv run pytest -q                          # 테스트
uv run ruff check src tests               # lint
uv run python -m ktide.generate --model-dir <dir> --condition <ID>   # 답변 생성
uv run python -m ktide.ingest <colab_output.txt> --condition <ID>     # Colab 출력 등록
uv run python -m ktide.judge <run_dir> --backend codex                # 교수님 Prompt로 채점
uv run python -m ktide.check_generation_config <model_dir>            # 실제 디코딩 설정 확인
```

## 8. 코드 구조

```text
src/ktide/
  professor.py               교수님 노트북을 실행 시점에 파싱(상수 + 함수 원문 실행)
  generate.py                교수님 load_model/answer_questions로 답변 생성, run 저장
  ingest.py                  외부(Colab) 출력을 run으로 등록
  judge.py                   Evaluation A: 교수님 Judge Prompt 채점
  metrics.py                 Evaluation B: 30어절, 문장 수, 언어 혼용 등 규칙 기반 지표
  artifacts.py               run 디렉터리, 스키마, 환경 정보
  check_generation_config.py 실제 적용되는 디코딩 설정 점검
docs/decisions/              결정 기록(ADR)
docs/progress/               단계별 진행 기록(집계 수치만)
```

새 모듈은 그 단계에서 실제로 필요할 때만 추가한다. 빈 파일이나 쓰지 않는 디렉터리를 미리 만들지 않는다.
