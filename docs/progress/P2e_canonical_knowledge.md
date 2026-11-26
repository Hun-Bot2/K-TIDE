# P2e 핵심 개념 집계

| 항목 | 값 |
|---|---:|
| 기존 개념 CKU 작성 | 191 / 191 |
| 새 개념 확정 | 0 |
| core_answer_ko 평균 어절 수 | 12.13 |
| v2 이미지 준비 | 270 / 270 |
| P2e 이미지 판독 | 0 / 270 |
| 강의 불일치로 기록된 개념 | 0 |

| 영역 | 개념 수 |
|---|---:|
| D01 | 30 |
| D02 | 17 |
| D03 | 21 |
| D04 | 28 |
| D05 | 25 |
| D06 | 5 |
| D07 | 15 |
| D08 | 9 |
| D09 | 26 |
| D10 | 15 |

| 근거 종류 | 필드별 표기 횟수 |
|---|---:|
| lecture | 354 |
| external_reference | 3 |
| model_knowledge | 1215 |

| 신뢰도 | 개념 수 |
|---|---:|
| high | 143 |
| medium | 47 |
| low | 1 |

## Claude 교차 검증 (CKU v1)

작성자(Codex)와 다른 모델(Claude, `claude-opus-5-5`)이 영역별로 나눠 191개 개념 전체를 검증했다.
검증 기준은 `prompts/claude_cku_review.md`에 있다. 각 개념의 인용 강의 페이지 텍스트를 직접 대조했다.

| 판정 | 개념 수 |
|---|---:|
| correct | 135 |
| minor_issue | 55 |
| incorrect | 1 |
| unclear | 0 |

| core_answer 점수(1~5) | 개념 수 |
|---|---:|
| 5 | 143 |
| 4 | 42 |
| 3 | 6 |
| 평균 | 4.72 |

- 검증자가 core_answer 수정안을 낸 개념: 33
- 강의 설명과 차이가 기록된 개념: 56 (작성자는 191개 모두 `consistent: true`로 기록)
- 반복된 문제 유형: 동의어가 아닌 alias, 핵심 이유("왜")가 빠진 core_answer, 단순 언급 페이지의 과다 인용,
  `preserve_english` 정책과 어긋난 표기, 비어 있는 오해·혼동 개념 항목
- 강의 자료 자체의 오류로 보이는 사례 2건을 기록했다(수치 표기 1건, 정규화 설명 1건). CKU에는 반영하지 않았다.

## CKU v2 집계

| 항목 | 값 |
|---|---:|
| 개념 | 191 |
| 수용 | 480 |
| 일부 수용 | 16 |
| 거절 | 1 |
| 강의와 불일치 | 2 |
| 강의 오류 주석 | 2 |
| core answer 평균 어절 수 | 13.32 |
| core answer 최대 어절 수 | 21 |
| 오해 항목 미작성 | 105 |
| 비교 항목 미작성 | 72 |

| 필드 변경 | 개념 수 |
|---|---:|
| basis | 191 |
| confidence | 191 |
| contrast_with | 101 |
| core_answer_ko | 123 |
| definition_ko | 125 |
| formula | 4 |
| lecture_alignment | 80 |
| limitations_ko | 8 |
| mechanism_ko | 14 |
| misconceptions_ko | 82 |
| open_questions | 48 |
| purpose_ko | 6 |
| sources | 76 |
| terminology | 39 |
| writer | 191 |

| 채움 | v1 | v2 |
|---|---:|---:|
| misconceptions_ko | 9/191 (4.7%) | 86/191 (45.0%) |
| contrast_with | 32/191 (16.8%) | 119/191 (62.3%) |

## CKU v2.1 집계

| 항목 | 수 |
|---|---:|
| CKU | 199 |
| 조사 교정 | 85 |
| 교정과 함께 문장 구조를 다듬은 필드 | 2 |
| 정리한 차이 설명 | 30 |
| 구체적인 차이와 출처를 기록한 설명 | 26 |
| 차이 설명을 비운 개념 | 4 |
| 검토한 이미지 페이지 | 270 |
| 판독 신뢰도 높음 | 268 |
| 판독 신뢰도 중간 | 2 |
| 판독 신뢰도 낮음 | 0 |
| 일부 영역 판독 불가 | 2 |
| 개념을 기록한 이미지 페이지 | 155 |
| 확대본에서 핵심 수식을 대조한 페이지 | 46 |
| 새 개념 | 8 |
| 시각 근거를 보강한 기존 개념 | 90 |

| 조사 교정 필드 | 건수 |
|---|---:|
| core_answer_ko | 37 |
| definition_ko | 36 |
| mechanism_ko | 0 |
| purpose_ko | 0 |
| limitations_ko | 0 |
| misconceptions_ko | 5 |
| contrast_with[].difference_ko | 6 |
| lecture_alignment.lecture_summary | 1 |
