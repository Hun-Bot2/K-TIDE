# 워크스테이션 GPU 실험 절차

통제 실험(M1~M4)은 모두 같은 워크스테이션 GPU에서 FP16으로 학습한다.
접속 주소와 계정은 이 문서에 쓰지 않는다. 로컬의 `data_private/workstation/config.json`(gitignore)에 둔다.

```json
{"host": "<user>@<workstation>", "remote_dir": "K-TIDE/data_private/workstation/outputs/",
 "local_dir": "data_private/workstation/outputs"}
```

## 1. 워크스테이션에서 학습 (SSH 접속 후)

```bash
cd ~/K-TIDE && git pull
uv sync --group train
export WANDB_API_KEY=...   # 값은 직접 입력, 파일에 저장하지 않는다
export HF_TOKEN=...
export CUDA_VISIBLE_DEVICES=0   # 공용 GPU면 비어 있는 번호
```

연결이 끊겨도 계속되도록 `tmux` 안에서 실행한다.

```bash
# smoke (8 step): W&B 기록과 FP16 점검(NaN/Inf 0, gradient scale)
uv run --group train --with ipykernel --with nbconvert jupyter nbconvert --to notebook --execute \
  --ExecutePreprocessor.timeout=-1 --output-dir /tmp --output gpu_train_smoke notebooks/gpu_train_lora.ipynb

# full: 학습 → 내보내기·검증 → during_development 답변 생성 → 결과 zip
KTIDE_RUN_MODE=full uv run --group train --with ipykernel --with nbconvert jupyter nbconvert --to notebook --execute \
  --ExecutePreprocessor.timeout=-1 --output-dir /tmp --output gpu_train_full notebooks/gpu_train_lora.ipynb

# M2 (영어 용어 보존, M1과 같은 번들·같은 QA 쌍): KTIDE_CONDITION=M2 를 앞에 붙인다
KTIDE_CONDITION=M2 KTIDE_RUN_MODE=full uv run --group train --with ipykernel --with nbconvert jupyter nbconvert --to notebook --execute \
  --ExecutePreprocessor.timeout=-1 --output-dir /tmp --output gpu_train_m2_full notebooks/gpu_train_lora.ipynb
```

조건·데이터를 바꿀 때는 M1·M2는 `KTIDE_CONDITION`(기본 `M1`)으로 고르고, 번들이 바뀌는 M3·M4는 노트북 설정 셀(`BUNDLE`, `BUNDLE_SHA256`, `QA`, `DATA`)을 바꾼다.
학습 파라미터, seed, `PRECISION = "fp16"`은 통제 실험에서 바꾸지 않는다.

## 2. 로컬로 결과 가져오기 (Mac)

```bash
cd ~/K-TIDE
uv run python -m ktide.sync_workstation
```

- rsync가 워크스테이션 비밀번호를 묻는다(VPN 연결 필요).
- 새 결과 zip만 골라 `runs/main/<조건>/`에 등록하고 규칙 기반 지표를 계산한다. 학습·평가 run은 W&B에 자동 기록된다.
- 이미 가져온 zip은 `data_private/workstation/imported.json`에 남아 다시 처리하지 않는다.

```bash
uv run python -m ktide.sync_workstation --dry-run     # 가져올 목록만 보기
uv run python -m ktide.sync_workstation --no-rsync    # 이미 복사한 zip만 등록
```

## 3. LLM Judge 채점 (Codex, 로컬)

```bash
uv run python -m ktide.evalset.score runs/main/<조건>/<run 폴더> --repeats 1 --split during_development --workers 4
```

채점 결과는 run 폴더에 캐시되고 W&B 평가 run에 자동 기록된다.

## 4. 확인

```bash
uv run python -m ktide.wandb_workspace --check   # 저장 뷰에 새 run이 보이는지 (읽기 전용)
uv run python -m ktide.figures                   # 로컬 비교 그림 (report_course/figures/dev)
```

W&B 뷰: `K-TIDE controlled (FP16)`, `K-TIDE pilot (BF16)` (URL은 `src/ktide/wandb_views.json`).
뷰 저장(`--save`)은 패널·레이아웃·필터 정책을 바꿀 때만 한다.
