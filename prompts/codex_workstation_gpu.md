# Codex 작업 지시: 워크스테이션 GPU에서 M1 FP16 학습 실행

권장 설정: reasoning medium. 이 저장소의 `AGENTS.md` 규칙을 따른다.
목표는 **환경 준비와 실행**이다. 학습 로직, 노트북, `src/` 코드는 수정하지 않는다.

## 배경

- 실행할 노트북: `notebooks/gpu_train_lora.ipynb` (Colab 노트북과 같은 단계, Colab 의존성 없음)
- 노트북은 HF dataset repo `HunBot/K-TIDE-Dataset`에서 번들(코드+데이터)을 받아 해시를 검증한 뒤
  `~/ktide_runs/` 아래에서 실행한다. 저장소 안에는 아무것도 쓰지 않는다.
- 연구용 학습은 FP16 고정(`PRECISION = "fp16"`), seed 42, 파라미터는 노트북 기본값 그대로 둔다.

## 작업

1. 저장소를 최신으로 맞춘다: `git pull` (브랜치 `p1-baseline-pipeline` 또는 사용자가 지정한 브랜치).
2. GPU와 드라이버를 확인한다: `nvidia-smi`. GPU 이름, 메모리, 드라이버/CUDA 버전, 다른 사용자의 사용 여부를 기록한다.
   공용 GPU면 비어 있는 GPU 번호를 골라 `CUDA_VISIBLE_DEVICES`로 지정한다.
3. 환경을 만든다:
   - `uv`가 없으면 설치한다(사용자 홈에 설치, sudo 불필요).
   - `uv sync --group train`
   - `uv run --group train python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"`
     로 CUDA 사용 가능 여부를 확인한다. `False`면 드라이버와 torch CUDA 버전이 맞지 않는 것이므로 원인을 보고하고 멈춘다.
4. 비밀 키: `WANDB_API_KEY`, `HF_TOKEN`은 **사용자가 직접** 셸에 export한다. 값을 묻거나 출력하거나 파일에 쓰지 않는다.
   설정 여부만 확인한다(`test -n "$WANDB_API_KEY" && echo set`).
5. **Smoke test** (기본값 `KTIDE_RUN_MODE=smoke`), 세션이 끊겨도 계속되도록 `tmux` 안에서 실행한다:
   ```bash
   uv run --group train --with ipykernel --with nbconvert jupyter nbconvert --to notebook --execute \
     --ExecutePreprocessor.timeout=-1 --output-dir /tmp --output gpu_train_smoke notebooks/gpu_train_lora.ipynb
   ```
   출력 노트북에서 다음을 확인해 보고한다:
   - 번들 해시 검증 통과, 패키지 버전 일치, GPU 이름
   - 마스킹 점검 결과(`masking OK; 294 examples`)
   - 학습 출력의 `"precision": "fp16"`, W&B run URL, `smoke test done` 줄
   - FP16 점검: `train/nonfinite_steps`(0이어야 함), `train/grad_scale_final`
6. Smoke가 정상이면 **사용자 확인을 받은 뒤** 전체 학습을 실행한다(노트북은 `KTIDE_RUN_MODE`로 모드를 받는다):
   ```bash
   KTIDE_RUN_MODE=full uv run --group train --with ipykernel --with nbconvert jupyter nbconvert --to notebook --execute \
     --ExecutePreprocessor.timeout=-1 --output-dir /tmp --output gpu_train_full notebooks/gpu_train_lora.ipynb
   ```
   보고할 것: W&B run ID, 학습 시간, 최종 train/validation loss, FP16 점검 값, 내보내기 검증
   (`professor_unpack_model: ok`, greedy), 답변 생성 문항 수(156), 업로드된 HF 경로(`results/M1/data-v1/<run id>.zip`).

## 하지 말 것

- `src/`, 노트북 원본, 테스트를 수정하지 않는다. 오류가 나면 전체 오류 메시지와 원인 추정을 보고하고 멈춘다.
- 커밋, push 하지 않는다. `runs/`, `data_private/`에 쓰지 않는다(모든 결과는 `~/ktide_runs/`).
- 비밀 키 값을 출력하지 않는다. 출력 노트북(`/tmp/*.ipynb`)을 저장소에 복사하지 않는다.
- 학습 파라미터, seed, 정밀도를 바꾸지 않는다.
