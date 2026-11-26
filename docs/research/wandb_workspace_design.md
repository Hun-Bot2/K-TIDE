# K-TIDE W&B Workspace 설계안

## No data 진단

W&B Public API로 `hun-bot/ktide`를 조회했다. 평가 Run 3개(B0 두 개, M0 한 개)와 데이터 Run 7개 모두 Summary가 있으며, 일반 History 및 System History 조회 결과는 10개 모두 빈 목록이었다. 현재 이관 코드는 `run.summary.update`로 집계만 저장하고 시스템 수집을 끈다. Trainer도 `report_to=[]`이며 학습 이력은 로컬에 저장하도록 작성되어 있다. 따라서 History 기반 패널에 표시할 점이 없다. 개별 패널의 실제 축과 필터는 브라우저에서 확인하지 않았다. Summary 기반 패널에서 No data가 뜨는 경우에는 선택된 Run의 정확한 키와 필터를 별도로 대조해야 한다.

## 패널 명세

| 섹션 및 판단 | 그래프와 축 | 집계 및 비교 조건 | 현재 상태 |
|---|---|---|---|
| Model Performance · 어떤 모델로 다음 실험을 진행할지 결정 | 점과 95% 신뢰구간. X 모델 조건, Y Reference 정답률. 별도 발산 점 그래프는 X Baseline 대비 차이(pp), Y 모델 조건 | 동일 평가셋 해시·split·Judge 설정의 같은 문항에서 비교. 반복 채점을 문항별 평균한 뒤 문항 평균, 복수 seed는 조건별 seed 평균과 개별 점 표시. 같은 문항 또는 variant group을 함께 재표집. 상대 개선율은 분모가 양수일 때만 100 × (모델 − Baseline) / Baseline으로 보조 표기 | M0 동결 전 기준점만 표시 가능. B0는 Course 별도 카드. 개선율 보류 |
| Dataset Construction · 증강으로 실제 범위가 늘었는지 판단 | 가로 막대 두 개. X QA 수 또는 개념 커버리지(%), Y 데이터셋 버전. 영역·질문 유형·질문 용어 표기별 가로 막대는 X 문항 비율, Y 범주 | 버전은 논리 이름과 해시로 연결. 고유 QA 수, QA가 있는 고유 개념 / 적격 개념 수를 각각 표시. 범주 비율은 해당 버전·split 내 분류 가능한 문항 기준이며 미분류 수 병기. CKU 개념 수는 별도 단위. M1·M2의 공통 QA는 한 번만 집계하고 조건별 입력 수와 답변 용어 정책은 따로 표시 | CKU 네 버전과 공통 QA 294개 및 조건별 입력 수 표시 가능. 분포는 범주별 집계 확인 후 추가 |
| Training Dynamics · 과적합과 학습 병목 확인 | 정렬된 선 그래프. X optimizer step, Y Training Loss·Validation Loss. 같은 X에 별도 Learning Rate 패널. GPU 사용률은 X 경과 시간, Y GPU별 활용률(%) | Run별 관측치를 보존하고 평가 간격 사이 결측을 보간하지 않는다. 동일 split과 학습 설정에서 Loss 비교. GPU는 장치·샘플링 간격이 같은 Run에서 비교 | 원격 training Run과 History 없음. Trainer 로그의 실제 step·loss·eval_loss·learning_rate를 확인 후 허용된 키만 이관. GPU는 실측 확보 후 추가 |
| Evaluation · 정답률과 출력 품질을 함께 확인 | 단위별 점 그래프. X 모델 조건, Y 정답률(%), 루브릭 평균(점), 용어 보존율(%), 길이·문장 제약 준수율(%). split별 패널 | Reference correct 판정의 문항별 반복 평균을 다시 평균. 루브릭은 반복 평균 후 문항 평균. 용어가 지정된 문항에서 문항별 보존 비율 평균. 30어절 이하 및 1~2문장 준수율은 각각 표시하고, 동시 준수율은 문항별 교집합으로 계산. 각 지표에 분모 표시 | M0의 split별 지표와 Course B0 일부 집계 사용 가능. M0 동시 준수율은 원자료 집계 필요 |
| Error Analysis · 개선할 영역과 실패 유형 우선순위 결정 | 영역별·질문 유형별 두 Heatmap. X 모델 조건, Y 영역 또는 질문 유형, 색은 M0 대비 정답률 차이(pp). 오류 유형별 점 그래프는 X 오류율, Y 오류 유형, 색은 모델 | 같은 split·문항·분류 체계로 비교하고 각 셀에 평가 문항 수 표시. 절대 정답률도 조회 가능하게 한다. 오류율의 분모는 해당 슬라이스의 검토 문항 수. 다중 라벨은 각 오류 유형에서 문항당 한 번 집계 | 로컬 평가기는 영역·질문 유형 집계를 산출하지만 이관은 split 중심. 오류 주석과 비교 모델 결과 확보 후 추가 |
| Research Comparison · 용어 보존과 지식 보강 효과 판단 | 2×2 상호작용 그래프. X 용어 보존 여부, Y 정답률, 선은 지식 보강 여부. 효과 점 그래프는 X 차이(pp), Y 사전 정의한 비교 | M2−M1·M4−M3은 용어 효과, M3−M1·M4−M2는 보강 효과. 상호작용은 (M4−M3)−(M2−M1). M0는 기준선. 평가 해시·Judge·학습 레시피를 맞추고 seen/unseen을 분리한다. seed와 문항 단위 불확실성을 반영한다 | 동결된 평가셋에서 M0~M4의 비교 가능한 결과가 나온 뒤 표시 |

참조 정답률과 루브릭은 별도 척도로 유지한다. B0의 과제 공개 문항과 M0 평가셋은 공통 개선율의 분모로 섞지 않는다. 빈 셀은 미측정으로 표시하고, 근거 부족으로 비교가 불가능한 패널은 구성에서 제외한다.

## 구현 근거와 적용 계획

- 비공개 단일 Project에서 Course와 Research Report의 기존 ID를 사용한다. 각 Report의 Run Set은 각각 `course`, `research` 태그로 제한한다. Research 최종 비교는 `evaluation_phase=final`, 비교할 조건, 평가 버전 및 split도 함께 제한한다. 현재 예비 평가와 데이터 구축은 해당 상태를 표시한다. 태그 필터는 화면 범위를 정하며 접근 권한은 Project에서 관리한다.
- Summary 수치는 버전별 막대와 평가 비교에 사용한다. 저장된 History를 요구하는 선 그래프는 실측이 생긴 후 활성화한다. 신뢰구간·차이·Heatmap은 기본 패널에서 표현할 수 있는지 확인하고, 필요하면 로컬에서 계산한 승인된 집계만으로 커스텀 패널을 구성한다. 원문·문항 ID·답변·개별 채점값은 이관하지 않는다. [W&B 공식 수치 로깅 안내](https://docs.wandb.ai/ko/support/models/articles/can-i-just-log-metrics-no-code-or-datase)
- `wandb-workspaces` 버전을 잠그고 Workspace 섹션·패널·필터 정의를 저장소에서 관리한다. SDK의 자동 패널 설정은 생성 시 적용된다. 기존 자동 Workspace는 앱에서 Manual 전환 가능 여부를 확인한다. 해당 경로를 사용할 수 없으면 자동 패널을 끈 관리 Workspace를 한 번 생성하고 고정 URL로 재사용한다. Run별 뷰와 프로젝트 기본 뷰의 범위는 실제 대상에서 확인한다. [SDK Quickstart](https://github.com/wandb/wandb-workspaces) · [Workspace 인터페이스](https://github.com/wandb/wandb-workspaces/blob/main/wandb_workspaces/workspaces/interface.py)
- 적용 전 조회 모드에서 대상 Project와 고정 Workspace·Report ID, 예상 섹션과 패널, 사용 가능한 Summary 키를 확인한다. 기존 객체를 URL로 불러와 관리 섹션과 필터를 교체한 뒤 저장한다. 적용 전 레이아웃은 비공개로 보관하며, 최초 생성이 필요한 관리 객체는 생성 후 반환된 ID를 고정해 이후 실행에서 재사용한다. 재적용 후 ID·패널 수·필터를 다시 읽고 Run ID 집합이 동일한지 확인한다. 기존 Report의 Run Set 필터도 다시 읽어 비교한다. [Reports 인터페이스](https://github.com/wandb/wandb-workspaces/blob/main/wandb_workspaces/reports/v2/interface.py)

이번 검토는 원격 조회와 설계 문서 작성까지 수행했다. Workspace 적용과 기존 Plot 제거는 설계 검토 이후 단계다.
