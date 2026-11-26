# ADR 0002 · W&B 실험 추적

기존 로컬 실험 기록을 원본으로 유지하고 W&B Python SDK로 사후 이관한다.
기존 Trainer, 평가 코드, 제출 노트북 및 Generation Configuration에는 변경이 없다.
학습 프로세스에 자동 로깅을 연결하면 실행 환경과 수집 대상이 함께 바뀌므로
P0에서는 저장된 수치만 명시적으로 선택한다. 동일한 run ID로
재시도하며 Public API에서 예상 config와 summary 값을 다시 읽어 대조한다.
[기존 run 재개](https://docs.wandb.ai/ko/support/models/articles/how-do-i-log-an-artifact-to-an-existing-)
[수치만 기록하기](https://docs.wandb.ai/ko/support/models/articles/can-i-just-log-metrics-no-code-or-datase)

## 규격 v2 (2026-11-26: 단일 프로젝트)

모든 연구 실험은 단일 W&B 프로젝트 `K-TIDE`(비공개, 2026-11-26 `ktide`에서 이름 변경)에서 관리한다. Course(기말과제)와
Research(학회 논문)는 W&B 안에서 tags, group, job type으로 나누고, Report는 Run Set의 tag 필터로 분리한다.
이 규격은 W&B 기록에만 적용된다. 저장소의 연구 구조(`report_course/`, `paper/`)와
로컬 실험 기록(`runs/`, `data_private/`)은 바꾸지 않으며, 이관 코드는 이를 읽기만 한다.

| 필드 | 값 | 의미 |
| --- | --- | --- |
| tags | `course`, `research` | 어느 트랙의 보고에 쓰이는지. 공통 run은 두 태그를 모두 가진다 |
| group | `baseline`, `knowledge`, `controlled`, `optimization` | 실험 계열 |
| job type | `data`, `training`, `evaluation` | 단계 |
| `condition` | B0, M0~M4, CKU-v*, lecture-only, ASSIGN 등 | 실험 조건 또는 데이터 이름 |
| `evaluation_phase` | `not_applicable`, `preliminary`, `final` | 평가 단계 |
| `input_datasets`, `output_datasets` | 논리 이름@SHA-256 | 데이터 버전 식별자 |
| summary | 고정 이름 숫자 지표 | 결측은 생략 |

분리 규칙:

- **통제 실험과 최적화 실험:** 논문용 2×2 통제 실험(M1~M4)은 group `controlled`,
  과제 제출 모델의 최적화 실험은 group `optimization`이다. `optimization` run에는
  `research` 태그를 붙일 수 없다(코드에서 거부).
- **M0~M4는 각각 독립 조건이다.** 조건마다 데이터, 학습, 평가 run을 따로 둔다.
- **과제 전용 결과:** 과제 공개 질문으로 측정한 결과(B0)와 `optimization` run은 `course` 태그만 갖는다.
  Research Report는 `tags contains research`로 걸러서 이 run들이 들어가지 않게 한다.
- **중복 금지:** run ID는 단계·조건·로컬 기록 식별자로 계산하고 트랙을 포함하지 않는다.
  공통 실험과 데이터는 한 번만 등록하고 태그로 두 트랙에 연결한다.
  예: M1·M2가 함께 쓰는 QA 구축은 `lecture-only` run 하나로 기록한다. M1(번역 용어 답변)과
  M2(영어 용어 보존 답변)는 학습에 쓰는 답변이 다르므로 각각 `M1-train@…`, `M2-train@…` 데이터 버전과
  run을 갖고, 입력으로 `lecture-only` 버전을 가리킨다. 학습·평가 run은 이 조건별 버전을 입력으로 기록한다.
- **조건이 다르면 별도 run:** 학습 설정, 데이터 버전, 평가셋, 평가 단계 중 하나라도 다르면 새 run이다.
- 데이터 파일은 비공개이므로 W&B 파일 Artifact로 올리지 않고, 버전 식별자로만 연결한다.

| Report | Run Set 필터 |
| --- | --- |
| K-TIDE · Research | `tags` in [`research`] (group으로 `controlled` 등 세분) |
| K-TIDE · Course | `tags` in [`course`] |

데이터 구축은 출력 버전, 학습과 평가는 실제 사용한 입력 버전을 기록한다.
CKU는 직전 버전과 연결하고 M1·M2 학습 데이터는 같은 QA 구축 버전에서 나온다.
B0의 Colab 실행은 공식 실행 환경에서 측정한 기준선이며 최종 평가 결과가 아니므로
CPU B0와 함께 예비 평가로 분류한다. M0는 평가셋 동결 전 결과다.
Track A 원천(B0 등)은 `course` 태그만 갖는다. 파일 경로와 원문을 payload에 싣지 않으며
파일 Artifact, 코드, 콘솔, 시스템 지표와 실행 환경의 자동 수집을 사용하지 않는다.

run ID는 단계, 조건, 로컬 기록 식별자로 계산한다. 같은 로컬 평가의 재시도는
기존 run을 재개한다. 데이터 내용이 바뀌면 버전과 run ID가 함께 바뀐다.
원격 쓰기에 실패하거나 검증이 중단되면 같은 명령으로 재시도할 수 있다.
이관 프로세스는 원본 경로에 쓰지 않으며 SDK의 임시 실행 파일은 별도 디렉터리에 둔다.

## 실행 및 확인

```bash
uv run python -m ktide.tracking
uv run python -m ktide.tracking --sync --entity <W-and-B-entity>
```

첫 명령으로 전송될 집계를 로컬에서 확인한다. 두 번째 명령은 현재 로그인으로
`K-TIDE` 프로젝트에 집계를 동기화하고 수치, 버전 식별자, tags, group, job type을 다시 읽는다.
계정 인증은 SDK 로그인 또는 환경 변수로 제공한다.

원격 run을 다시 만들어야 할 때(예: 서버에서 지워지지 않는 summary가 남은 경우)는 그 run ID를
`tracking.py`의 `RETIRED_RUN_IDS`에 올린다. W&B는 지운 run의 ID를 다시 쓰지 않으므로 대체 run은
기존 ID에서 계산한 새 ID를 받는다. 삭제는 목록에 있는 run만, run마다 `yes`를 입력해야 실행된다.

```bash
uv run python -m ktide.tracking --retire --sync --entity hun-bot
```

### 기록

규격 v1(두 프로젝트)에서 이관 후보 9건을 확인했다. CKU v1·v2·v2.1·v3는 각각 191·191·199·199건이고
v3의 교재 근거 표기 448건은 기존 집계와 일치한다. M1·M2는 각각 294개 QA를 공유한다.
pytest 27개와 Ruff를 통과했다. SDK 모의 테스트로 동일 ID 재시도와
원격 수치 불일치 검출을 확인했다.
2026-11-26에 위 두 프로젝트의 기존 run ID 9개에서 로컬 집계와 원격 summary를
대조했다. 생성 직후 Public API에서 빈 값이 일시적으로 반환됐으며 새 연결에서는
모든 집계가 일치했다. 표시 이름도 같은 ID에서 변경한 뒤 원격에서 확인했다.
초기 동기화에서 SDK가 자동 생성한 패키지 목록을 전송했다. 이후 실행에서는
`x_save_requirements=False`를 적용했다. 2026-11-26 이름 변경 후 pytest 28개와
Ruff를 통과했다.

2026-11-26 규격 v2로 `hun-bot/ktide`에 8개 run을 이관했다(B0 2, M0 1, CKU 4, lecture-only 1).
첫 실행은 생성 직후 summary가 비어 있어 검증에서 멈췄고, 같은 명령을 다시 실행해 8개 모두
config, summary, tags, group, job type이 로컬 집계와 일치함을 확인했다. `paper` 필터에는
B0가 포함되지 않는다. 규격 v1의 `ktide-course`, `ktide-research` 프로젝트는 남아 있으며
삭제 여부는 사용자가 결정한다. pytest 28개와 Ruff를 통과했다.

같은 날 규격을 보완했다: 트랙 태그를 `paper`에서 `research`로 바꾸고, 합쳐 두었던 M1·M2 데이터를
공통 QA 구축 run(`lecture-only`)과 조건별 학습 데이터 run(M1, M2)으로 나눴다(run 10개).
공통 run에 남아 있던 조건별 summary 2개(`answer/*/mean_words`)는 Public API와 재개한 SDK run에서
삭제를 시도했으나 서버에 반영되지 않았다. 그래서 이 run(`6ba599ce…`)을 `RETIRED_RUN_IDS`에 올리고
새 ID(`15138ff8…`)로 다시 만들도록 했다. 삭제와 재생성은 사용자가 위 명령으로 실행한다. 재동기화 후 10개 모두
예상 config, summary, tags, group, job type과 일치를 확인했고,
`K-TIDE · Research`, `K-TIDE · Course` Report를 만들어 저장된 Run Set 필터를 다시 읽어 확인했다.
Report 생성에는 `wandb-workspaces`를 일회성으로만 사용했다(프로젝트 의존성에 추가하지 않음).

## 규격 v3 (2026-11-26: 자동 기록과 코드 기반 Workspace)

- **학습은 실시간 기록한다.** `ktide.train.sft --report-to wandb`가 Trainer보다 먼저 run을 열고 Trainer의
  W&B callback이 그 run을 이어 쓴다(`train/loss`, `train/learning_rate`, `train/grad_norm`, `eval/loss`,
  x축 `train/global_step`). GPU 지표는 SDK가 5초 간격으로 수집한다. `WANDB_LOG_MODEL=false`,
  `WANDB_WATCH=false`, 코드·콘솔·requirements 수집은 끈다. 네트워크 장애 시 offline으로 계속 학습하고,
  학습이 실패해도 `train_config.json`(status=failed)과 `train_log.json`을 남긴다.
- **Run ID:** 일반 학습은 노트북이 만든 ID(`--run-id`), Sweep은 agent가 정한 ID를 쓴다. 어느 쪽이든 실제
  W&B run ID가 출력 폴더(`/content/outputs/<id>`), 답변 run 폴더 이름, HF 결과 경로
  (`results/<condition>/<data>/<id>.zip`), `train_config.json`의 `wandb_run_id`가 된다.
- **실험 식별자:** `experiment_id = <condition>/<live run id 또는 run 폴더>`를 학습 run과 평가 run이 함께 갖는다.
  학습 run(job type `training`)과 평가 run(`evaluation`)은 따로 둔다. 실시간 run이 있으면 사후 이관은 새 run을
  만들지 않고 그 run에 내보내기 검증 결과만 더한다.
- **자동 기록 지점:** 결과 Import(`import_colab`), 규칙 기반·LLM Judge 평가(`evalset.score`, 슬라이스별 오류 분석
  집계 포함), 데이터셋 구축(`train_data.lecture_only_qc`, `knowledge.polish_cku`, `knowledge.slp revise`)이 끝나면
  `tracking.record()`가 해당 run만 동기화한다. 기록 실패는 파이프라인을 멈추지 않고 재시도 명령을 출력한다
  (`KTIDE_WANDB=0`으로 끔).
- **이름:** 개발 중 평가 split은 기록과 시각화에서 `during_development`로 부른다(문항 ID 접두어 `dev-`는 유지).
  M0 run에 남은 기존 `/dev/` 키는 지우지 않고 관리 패널에서 쓰지 않는다.
- **Workspace:** `ktide.wandb_workspace`가 자동 생성 패널을 끈 팀 저장 뷰를 코드로 정의하고, URL을
  `src/ktide/wandb_views.json`에 고정해 같은 뷰를 갱신한다(개인 Workspace는 W&B API가 지원하지 않아 대상이 아니다).
  run 필터는 동적이다: `tags in [research] and config.stage in [training, evaluation]`. 조건 이름이나 run ID를 쓰지
  않으므로 M2~M4와 후속 모델의 학습·평가 run은 저장 없이 같은 패널에 나타난다. 데이터 run, B0, 과제 최적화 run,
  smoke run은 필터에서 빠진다. `--save`는 패널·레이아웃·필터 정책을 바꿀 때만 실행하고, 새 run 반영 확인은 읽기 전용
  `--check`로 한다. run과 데이터는 지우지 않는다.
- **번들:** `bundle_manifest.json`(git commit·dirty, 파일별 SHA-256, 학습 데이터 해시, 분리 점검 결과)을 넣고,
  노트북은 ZIP 해시(`BUNDLE_SHA256`)와 파일 해시가 다르면 멈춘다. 압축은 번들 해시별 폴더에 푼다.
- **정밀도:** BF16은 compute capability 8.0 이상에서만 쓴다. M1(data-v1, run `5215e607…`)은 실제 실행 조건인
  BF16(T4 에뮬레이션)으로 기록되어 있으며, 이후 FP16 재학습은 별도 run이다. **연구용 학습은 FP16으로 통일한다**
  (2026-11-26 결정, 교수님 평가의 FP16 추론과 일치). 노트북이 `--precision fp16`을 명시한다.
- **Smoke test:** `--track smoke --max-steps N`. 태그 `smoke`, group `smoke`로 두어 Course·Research Report와
  사후 이관에서 제외한다.
- **실험 단계(study_phase, 2026-11-26):** M0 = `baseline`, BF16 M1(data-v1) = `pilot`(삭제·덮어쓰기 없이 보존),
  FP16 연구 run = `controlled`, 과제 최적화 = `optimization`, smoke = `smoke`. 학습 run은 `sft.py`가 실시간으로,
  사후 이관은 `tracking.study_phase()`가 기록한다. 저장 뷰 두 개가 같은 패널을 쓰고 필터만 다르다:
  `K-TIDE controlled (FP16)`(baseline+controlled), `K-TIDE pilot (BF16)`(baseline+pilot).
- **비교 지표:** Knowledge Accuracy(strict accuracy, reference score, judge accuracy)와 Instruction Following
  (30어절, 1~2문장, 둘 다, judge constraints)을 나눠 보인다. 평가 run마다 M0 대비 변화량(`delta_vs_M0/*`, 같은
  문항 수일 때만), 문항별 개선·유지·하락 수(`paired_vs_M0/*`), during_development 문항만으로 만든 영역별 히트맵
  (집계 PNG, `heatmap/*`, 내용 해시가 바뀔 때만 다시 올림)을 기록한다. 이 값들은 차이를 보여 줄 뿐 유의성 검정이나
  인과 판단이 아니다.
- **FP16 점검:** 학습 중 gradient scale 변화(감소 = overflow로 건너뛴 step)와 loss·grad norm·eval loss의 NaN/Inf
  횟수를 `train/grad_scale_*`, `train/nonfinite_steps`로 기록한다(관찰만 하며 학습 동작은 바꾸지 않는다).
