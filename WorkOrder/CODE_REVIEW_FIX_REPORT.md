# 코드 리뷰 F1~F6 수정 보고 — 2026-10-26

시작 HEAD와 리뷰 기준은 모두 `829e24c932dbaaaf61bacc8b7dd449decdff6df4`였다.
사용자가 추가한 작업 지시서 외 기존 변경은 없었다. 실제 수집 자료에는 오류를 주입하지 않았고,
pytest 임시 경로와 새 synthetic 출력만 사용했다. 기존 v2 reader·원본 acquisition·영상은 유지한다.

## 수정 전 재현과 원인

Windows/Python 3.12.8에서 기준 시험은 **81 passed in 13.63s**였다.
지시서의 Linux 6.63초 결과와 환경·실행 시간이 다르며, 시험 개수는 동일했다.
신규 최소 재현 `tests/test_review_fix_regressions.py`를 수정 전에 실행한 결과
**6 failed in 9.35s**였다. [실제 실패 출력](CODE_REVIEW_BASELINE_FAILURES.txt)에 보존했다.
같은 재현 파일은 수정 후 **6 passed in 8.62s**로 확인했고 이후 전체 시험에도 포함했다.

| ID | 재현 조건 / 원인 | 수정 위치 | 확인 결과 |
|---|---|---|---|
| F1 | 장치 100ms EMG가 host 600ms에 도착하면 receipt로 pose를 선택. fit 결과가 연결에 미사용 | sync/clock_alignment.py, labeling/sample_labels.py, storage/training_pipeline.py, controller, review UI | 알려진 500ms 지연에서 100ms pose 선택. drift·epoch·burst·미래 receipt/infer/mapping 차단. receive 회귀의 잔차가 작아도 미검증. mapping 변경 시 재평가 |
| F2 | 3초마다 1개만 남긴 EMG도 파일 구조가 맞으면 정상 15예제 export. mask에 시간 공백 미표현 | quality/window.py, multimodal/validator.py, eligibility.py, training_pipeline.py | 희소 데이터 0예제. 500Hz/jitter 허용. 긴 gap·양 경계 공백·clipping·중복 burst·epoch 교차 제외. 불규칙 시각/gap/epoch 보존 |
| F3 | 최초 정상 샘플 이후 timeout 조건이 없어 무응답 지속. malformed continue가 timeout 검사 우회 가능 | acquisition/watchdog.py, multimodal/controller.py, camera_worker.py, multimodal_writer.py, 수집 UI | 가짜 시계로 시작 무응답/1샘플 후 정체/지속 malformed/일시 지연 회복/disconnect/stop 경합. bounded writer 종료. 장애 reason 유지·incomplete·원본 보존 |
| F4 | 미완료 한 세션의 validator 오류가 모든 정상 export를 중단 | multimodal/eligibility.py, storage/training_pipeline.py, CLI/UI | 정상+손상+미완료 root에서 정상 15예제와 분리 집계. strict 실패와 주입한 I/O 실패에 complete 출력 없음. 입력 해시 유지 |
| F5 | top 전 시작 자세 복귀 전이가 없어 여러 부분 컬을 하나로 합침. UI에서 시도 복구 불가 | labeling/repetitions.py, edits.py, validation.py, ui/review_editing.py | 부분 컬 3회는 invalid 3개. 추적 유실은 unknown 우선. finish 중복 없음. Qt 추가/삭제/분할/병합→저장→재열기→CSV. 삭제한 terminal 참조 차단·phase 순서 검사 |
| F6 | 이전 objective=False도 reviewer ID가 다르면 조정으로 confirmed 가능 | labeling/review_contract.py, review.py, validator, 검토 UI | 미완료/동일 reviewer/legacy 판정으로 확정 불가. 두 완료 독립 평가 일치 또는 명시 조정 필요. stale CAS/정렬 변경/근거 누락 시 exact 해제. manifest 저장 실패 후 거래 복구 |

F5 UI 경로 시험 중 선택된 행이 있는 상태의 “추가”가 해당 행을 제거하는 문제도 발견했다.
추가는 현재 선택을 삭제 대상으로 사용하지 않도록 수정했고, 단계별 행 수와 생성 ID를 검증했다.

## 변경 계약과 사용자 영향

부모 스키마 3.0.0은 유지하며 `alignment-1`, `emg-quality-1`, `watchdog-1`,
`review-2`, 구현 계약 `review-fixes-1`을 기록한다.
필드·허용값·호환 별칭은 [데이터 사전](MULTIMODAL_V3_SCHEMA.md),
실행 순서는 [수집/검토 안내](MULTIMODAL_V3_GUIDE.md)에 정리했다.

물리 측정시각과 수신·추론 가용 시점을 분리했다. real receive 회귀는 latency bias를 분리할 수
없으므로 미검증이며 기본 학습 export에서 제외한다. `--allow-unverified-alignment` 또는
UI 진단 체크는 명시적 파일럿 진단 경로다. 경고/집계를 기록하고 training_ready=False로 둔다.
실제 동기 오차를 임의로 0 또는 500ms로 대체하지 않는다. 새 reference mapping은
publish_alignment()로 파생 파일을 발행하며 sync 원본을 보존한다.

기존 자동 파일은 유지한다. 근거가 없는 과거 confirmed는 새 정책에서 provisional로 취급한다.
같은 로컬 ID 입력만으로 사람 신원을 인증하지 않으며, 독립 검토 운영 책임은 연구자에게 있다.
검토 UI는 독립/조정/초안을 구분하고 독립 판정은 원 acquisition에서 시작한다.
저장 API는 완료 독립 평가에 expected_revision과 evidence를 요구한다.
이전 호출 형식의 append_review는 호환 초안으로 남고 객관적 완료 평가로 자동 승격되지 않는다.

quality는 연구 검증된 표준이 아닌 PILOT 공학 후보값이다. 500Hz/450~550Hz/커버리지0.9/
gap20ms/clipping0.05/불확실성50ms/결정지연500ms/epoch 교차 금지가 기본값이다.
정책 변경은 export manifest의 실제 값·fingerprint로 추적한다.
validator 무결성 API는 유지하고 inspect_session과 CLI --quality-report가 품질을 별도로 반환한다.

기본 export는 관련 미완료/손상/미검토/검열 세션을 격리하며 제외 사유를 숨기지 않는다.
출력 덮어쓰기 금지와 staging→manifest 마지막→공개 순서를 적용했다.
0예제와 빈 split은 표시한다. participant split은 여전히 window 생성 전에 정한다.

## 실제 실행 결과

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.venv\Scripts\python -m pytest -q
# 118 passed in 68.48s (0:01:08)
.venv\Scripts\python scripts/create_synthetic_dataset.py datasets/review_fixes_20261026
.venv\Scripts\python scripts/validate_dataset.py datasets/review_fixes_20261026 --quality-report build/review_fix_quality.json
# OK: dataset passed all integrity checks
.venv\Scripts\python scripts/export_training_dataset.py datasets/review_fixes_20261026 datasets/review_fixes_training_20261026 --synthetic --allow-pilot --strict
# 15 examples; sessions={'eligible':1}; window exclusions={}; empty splits=['validation','test']
```

합성 예제는 24,001 EMG samples, 481 frames, 15 유효+1 실패 시도이며
무결성 오류0, 500Hz, 커버리지1.0, 최대 gap2ms, clipping0, epoch1로 관찰됐다.
검토된 잔여 라벨 k=10/14/15는 5/1/0이다(기존 통합 회귀 시험 유지).
한 참가자 예제여서 validation/test가 비어 있으며 학습 준비 완료로 표시하지 않는다.
미검증 mapping 테스트는 기본0예제/명시 진단15예제 및 경고를 확인한다.
시험 로그는 build/review_fix_tests.txt, quality JSON과 예제 데이터는 Git 제외 경로에 있다.

Python3.12.8, PyQt6 6.7/Qt6.7.1, numpy1.26.4, mediapipe0.10.21,
OpenCV4.10.0.84에서 실행했다. 수정 파일 Ruff F 검사도 통과했다.
저장소 기존 미수정 파일의 unused import 3건은 이번 변경에 포함하지 않았다.
Windows EXE의 최종 해시와 자체 시험 결과는 [빌드 보고](WINDOWS_EXE_BUILD.md)를 참조한다.
이번 소스로 재빌드한 EXE 자체 시험과 Python 경로 제거 독립 실행은 모두 exit0/ok=true였다.
독립 실행은 EMG/통합 라벨500행, 영상22프레임, validator 오류0을 확인했다.

실제 ESP32·카메라 동시 연결과 물리 동기·DPI/다중 모니터 조합은 이번에 검증하지 않았다.
실장치 파일럿에는 기준 이벤트와 하드웨어 측정이 필요하다. 합성 일치는 실제 정확도의 증거가 아니다.
