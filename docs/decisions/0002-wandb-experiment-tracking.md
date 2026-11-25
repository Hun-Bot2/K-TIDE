# ADR 0002 · W&B 실험 추적

기존 로컬 실험 기록을 원본으로 유지하고 W&B Python SDK로 사후 이관한다.
기존 Trainer, 평가 코드, 제출 노트북 및 Generation Configuration에는 변경이 없다.
학습 프로세스에 자동 로깅을 연결하면 실행 환경과 수집 대상이 함께 바뀌므로
P0에서는 저장된 수치만 명시적으로 선택한다. 동일한 run ID로
재시도하며 Public API에서 예상 config와 summary 값을 다시 읽어 대조한다.
[기존 run 재개](https://docs.wandb.ai/ko/support/models/articles/how-do-i-log-an-artifact-to-an-existing-)
[수치만 기록하기](https://docs.wandb.ai/ko/support/models/articles/can-i-just-log-metrics-no-code-or-datase)

## 규격 v2 (2026-11-26: 단일 프로젝트)

모든 연구 실험은 단일 W&B 프로젝트 `ktide`(비공개)에서 관리한다. Course(기말과제)와
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
`ktide` 프로젝트에 집계를 동기화하고 수치, 버전 식별자, tags, group, job type을 다시 읽는다.
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
