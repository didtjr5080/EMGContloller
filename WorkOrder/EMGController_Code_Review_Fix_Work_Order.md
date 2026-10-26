# EMGContloller 코드 리뷰 후속 수정 작업 지시서

작성일: 2026-10-26 (한국 시간)  
대상 저장소: https://github.com/didtjr5080/EMGContloller  
리뷰 기준 커밋: `829e24c932dbaaaf61bacc8b7dd449decdff6df4`

## 1. 작업 목표와 적용 규칙

EMG와 자세의 시간 연결, 신호 결측, 수집 중단, 세션 내보내기, 부분 반복, 검토 확정에 관한 6개 결함을 수정하라. 기능을 새로 전면 구현하거나 예측 모델을 선정하는 작업이 아니다. 기존 PyQt6·MediaPipe·이두/삼두 수집 구조와 v2 판독을 유지한다.

작업 시작 시 현재 HEAD와 AGENTS.md를 확인하고, 리뷰 커밋 이후 변경을 먼저 비교하라. 이미 해결된 항목은 재현 테스트로 확인한 뒤 완료로 표시한다. 최신 코드를 과거 리뷰 커밋으로 되돌리지 않는다. 실제 참가자 원본·영상·기존 판정 기록은 덮어쓰지 않는다.

각 결함은 **최소 실패 테스트 작성 → 수정 전 실행 → 원인 기록 → 최소 수정 → 동일 테스트 재실행** 순서로 처리한다. 가짜 시계·합성 데이터·모의 장치로 검증하며 실제 장치나 참가자 데이터에 오류를 주입하지 않는다. 이 문서의 관측 결과는 이전 리뷰에서 확인한 사실이고, 수정 완료 결과가 아니다.

## 2. 확인된 결함과 우선순위

| ID | 우선순위 | 확인한 현상 | 수정 중심 경로 |
|---|---|---|---|
| F1 | P1 | 측정 시각 대신 수신 시각으로 자세·반복 연결 | `sync/clock_alignment.py`, `labeling/sample_labels.py`, `storage/training_export.py`, `multimodal/controller.py` |
| F2 | P1 | 3초마다 EMG 1개뿐이어도 검증·학습 export 통과 | `multimodal/validator.py`, `storage/training_export.py`, 품질 모듈 |
| F3 | P1 | 첫 정상 샘플 이후 수신 중단 watchdog 없음 | `multimodal/controller.py`, 수집 UI |
| F4 | P2 | 미완료 세션 1개가 정상 세션 전체 export 차단 | `storage/training_export.py`, UI·CLI |
| F5 | P2 | 목표 각도 미달 후 시작 자세 복귀 시 반복 종료 안 됨 | `labeling/repetitions.py`, `ui/multimodal_review.py`, 검토 검증 |
| F6 | P2 | 첫 검토 objective=False여도 두 번째 조정으로 confirmed 가능 | `labeling/review.py`, 검토 UI·validator |

기존 테스트의 리뷰 시 재실행 결과: Linux·Python 3.12, `QT_QPA_PLATFORM=offscreen python -m pytest -q` → **81 passed in 6.63s**. 새 HEAD에서 다시 실행하고 결과가 달라지면 그 이유를 기록한다. Windows EXE·실제 ESP32·실제 카메라 동기 오차는 이 수치로 검증됐다고 주장하지 않는다.

## 3. F1 — 측정 시각과 수신 시각을 구분한 정렬

### 실패 재현

장치 시각 100ms의 EMG가 host 600ms에 도착하는 합성 예를 만든다. host 100ms와 600ms에는 서로 다른 팔꿈치 각도의 pose가 있다. 현재 `labeled_rows()`는 600ms pose를 선택하고 pose_valid=True로 반환한다. `fit_clock()` 결과가 저장되더라도 연결에는 사용되지 않는다. 동일 문제가 반복 구간·window 선택에도 존재한다.

### 수정 요구사항

1. 원본 `device_time_us`, `unwrapped_time_us`, `epoch_id`, `host_receive_ns`, `capture_host_ns`, `infer_host_ns`를 유지한다. 별도 파생 필드 또는 파생 alignment 테이블로 `measurement_host_ns`, `alignment_status`, `alignment_uncertainty_ns`, `mapping_version`을 제공한다.
2. **물리적 측정 시각**과 **예측 시점에 사용 가능해진 시각**을 분리한다. EMG/pose의 시간적 대응은 측정·촬영 시각으로 판단하고, 예측 입력에 포함 가능한지는 수신·추론 완료 시각으로 판단한다.
3. epoch별 clock mapping을 한 곳에서 정의하고 샘플 라벨, 세트/반복 연결, 검토 타임라인, 학습 export에서 공통으로 사용한다. epoch를 넘어 연결하거나 보간하지 않는다.
4. 장치-호스트 기준 이벤트 또는 알려진 합성 mapping이 있을 때 알려진 지연을 보정할 수 있어야 한다. 수신시각 회귀만으로는 일정한 전송 지연과 clock offset을 분리할 수 없으므로, 임의로 500ms를 추정해 빼거나 실제 동기가 맞았다고 주장하지 않는다.
5. software-only 추정은 추정 상태·잔차·관측 구간·알 수 없는 latency bias를 기록한다. 물리적 오차 미측정을 잔차가 작다는 이유로 0으로 바꾸지 않는다. 프로토콜의 동기 허용 조건을 만족하지 못하면 alignment_unverified로 표시하고 엄격 학습 export에서 제외한다. 파일럿 진단 export는 명시적 opt-in과 경고·집계가 있어야 한다.
6. 세트 전체를 사용해 fit한 mapping은 사후 검토용으로만 구분한다. 실시간 성능을 주장하는 학습 입력에는 예측 의사결정 시점 이전 관측으로 얻은 mapping만 사용한다. 미래 관측을 사용하는 fit·보간을 숨기지 않는다.
7. `prediction_capture_ns`와 `decision_host_ns` 등 필드의 의미를 명시한다. 반복 완료는 촬영 직후가 아니라 해당 프레임 추론·debounce가 완료된 뒤 알려질 수 있다. decision 시점보다 늦게 수신/추론된 자료는 입력에서 제외한다. 과거 EMG가 나중에 도착했다고 이전 예측 입력에 소급 추가하지 않는다.
8. 정렬 버전이 바뀌면 자동 라벨과 검토 근거에 사용한 버전을 남긴다. 기존 reviewed 결과를 새 정렬의 confirmed 결과로 조용히 재사용하지 않는다. 근거가 달라진 파생 산출물은 재검토 필요 상태로 관리한다.
9. acquisition 중 늦게 수신한 EMG를 저장할 종료 유예가 필요하다면 그 기간과 원래 운동 종료 경계를 분리한다. 유예 중 동작을 원 세트에 추가하지 않는다.

### 완료 기준

- 알려진 mapping·500ms 지연 fixture는 올바른 촬영 시각에 연결된다.
- mapping 불명 fixture는 정상 동기 데이터로 통과하지 않는다.
- burst 수신·drift·epoch reset·큰 gap fixture에서 정렬 상태가 재현된다.
- 미래 수신·추론·미래 mapping 관측이 과거 의사결정 입력에 들어가지 않는다.
- 정렬 오차가 확인되지 않은 실제 장치를 validated로 표시하지 않는다.

## 4. F2 — window별 EMG 품질 기준과 mask

### 실패 재현

48초·500Hz·24,001행 합성 데이터에서 1,500행마다 1행만 남기고 sample_index와 실제 행수·manifest를 일관되게 갱신한다. 실측률 약 0.333Hz와 추정 결측량도 기록한다. 리뷰 시 validator 오류는 없었고 export는 15개 예제를 생성했으며 첫 window에 샘플 2개만 존재했다. EMG mask도 모두 True였다.

해시는 무결성 검증이며 신호 품질 검증을 대신하지 않는다는 점을 테스트로 고정한다.

### 수정 요구사항

1. 프로토콜과 분리 가능한 버전별 `quality_policy`를 정의한다. 예상/허용 샘플링률, 최대 연속 gap, 최소 커버리지, clipping 허용, 최대 clock 불확실성, epoch 교차 허용 여부를 명시한다. 수치는 연구에서 검증된 표준이라고 주장하지 말고 설정 근거와 PILOT 상태를 남긴다.
2. window별 `expected_samples`, `observed_samples`, `coverage_ratio`, `max_gap_ns`, `clipping_ratio`, `epoch_count`, `alignment_status`와 제외 사유를 계산한다. 커버리지는 시간 간격을 함께 보아 burst·중복 시각으로 부풀리지 못하게 한다.
3. 샘플이 한 개라도 있다는 이유로 통과시키지 않는다. 시간 경계를 포함한 gap·커버리지 부족·epoch 교차는 정책에 따라 제외한다. window 이전 정상 샘플을 끌어와 결측을 가리지 않는다.
4. EMG mask의 의미를 명확히 한다. 규칙적 grid로 재표본화한다면 결측 위치는 False로 기록하고 보간 한계를 지킨다. 불규칙 원시 sequence를 유지한다면 timestamp·gap 정보를 함께 제공하고, 사라진 시점이 표현되지 않은 all-True mask를 연속 정상 수집의 증거로 사용하지 않는다. 기본 비교 경로에는 심한 gap window 제외를 적용한다.
5. 재부팅 경계나 큰 gap을 이어 붙여 CNN/LSTM에 연속 파형처럼 제공하지 않는다. 부분 길이 초기 window를 허용할 경우 길이·커버리지 계산 기준을 문서화한다.
6. validator는 파일/참조 무결성과 품질 상태를 별도로 반환하도록 확장한다. 현재 공개 API가 오류 리스트를 반환하는 점은 호환 wrapper 또는 버전별 adapter로 유지할 수 있다.
7. 학습 export는 모든 modality 비교에 동일한 공통 index를 사용하고 제외 이유·개수·사용 policy를 manifest에 남긴다. 제외율을 감추지 않는다.

### 완료 기준

- 위 0.333Hz fixture는 엄격 export에서 예제 0개이며 구체적 품질 사유가 집계된다.
- 정상 500Hz fixture와 허용 범위 안의 jitter는 통과한다.
- 큰 gap·클리핑·epoch 교차·앞뒤 경계 결측 테스트가 통과한다.
- 품질을 통과한 window만 학습 입력에 들어간다. 정상 가변 길이와 결측을 구분한다.

## 5. F3 — 시작·수집 중 watchdog과 장애 상태

### 실패 재현

모의 serial이 일치하는 헤더와 정상 샘플 1개를 반환한 뒤 빈 bytes를 계속 반환하게 한다. 리뷰에서는 5.3초 후에도 sample_count=1, errors=[], stop_event=False, thread_alive=True였다. 현재 5초 timeout은 최초 sample_count==0 조건에서만 실행된다.

### 수정 요구사항

1. `last_valid_sample_monotonic_ns`를 정상 샘플에만 갱신한다. 빈 응답, boot 로그, 잘못된 행이 들어와도 수신 watchdog을 연장하지 않는다.
2. 시작 유효 데이터 대기와 수집 중 정상 샘플 정지 timeout을 각각 설정한다. watchdog 검사는 parse 성공 여부와 관계없이 매 loop 실행되도록 한다. malformed 행에서 continue만 반복하며 timeout을 우회하지 않게 한다.
3. 일시 jitter는 configurable grace로 허용하고, 임계값 초과 시 `serial_stall` 또는 구체적 장치 오류 이벤트·마지막 정상 시각·발견 시각을 남긴다. 세트 종료 사유는 equipment_failure로 기록하고 manifest는 incomplete, exact 라벨은 미확정으로 둔다.
4. 수집 중 단절 감지와 worker 예외가 모두 동일한 중지·finalize 절차로 수렴하게 한다. 사용자 stop과 장애가 경합하면 장애를 숨기지 않는다. 초기화 실패·비어 있는 필수 stream도 성공 완료로 표시하지 않는다.
5. 마지막 소량 정상 샘플과 영상은 보존한다. 자동 재연결을 기존 세트의 연속 데이터처럼 붙이지 않는다. 구현할 경우 새로운 epoch/세트 경계와 품질 표시가 필요하다.
6. UI에는 고정된 sample count를 정상 진행처럼 보여주지 않고, 정지 사유와 미완료 상태를 표시한다. 카메라 또는 pose가 계속 멈췄는지도 동일 원칙으로 검토한다.
7. writer/worker 종료에 상한을 두고, 타임아웃이면 미완료를 남긴다. 블로킹 I/O를 강제로 정상 완료 처리하지 않는다.

### 완료 기준

가짜 시계를 사용해 5초 실대기 없이 다음을 검증한다: 첫 샘플 전 무응답, 한 샘플 후 무응답, 지속 malformed, 일시 지연 후 회복, 명시적 disconnect, 사용자 중지와 경합. 장애 fixture는 오류가 남고 confirmed/exact가 생기지 않아야 한다. watchdog 테스트에 실제 ESP32를 요구하지 않는다.

## 6. F4 — 정상 세션 export와 실패 세션 격리

### 실패 재현

정상 검토 완료 세션과 동일 synthetic 모드의 미완료 세션을 한 root에 놓는다. 미완료 쪽 metadata만 존재하거나 manifest.status=incomplete인 경우를 각각 만든다. 현재 `validate_session()` 오류 즉시 raise로 정상 세션도 export되지 않는다.

### 수정 요구사항

1. 세션별 `eligible`, `incomplete`, `recovered`, `unreviewed`, `censored`, `corrupt`, `wrong_schema`, `different_mode`, `quality_failed` 등 상태를 분류한다.
2. 기본 모드는 미완료/복구/미검토/중도중단 세션을 제외하고 정상 세션을 계속 처리한다. validator 전체를 생략해 손상 데이터를 사용하지 않는다.
3. 손상·의미 충돌 세션도 오류 내역과 함께 격리하고 정상 세션 export를 완료하되, CLI는 이를 명시적으로 보고한다. 전체 중단이 필요한 사용자를 위해 `--strict`를 제공한다. 원본을 이동·삭제해 문제를 감추지 않는다.
4. `exclusion_report.json` 등으로 session_id, 상태, 오류 code·field, 집계 단위를 남긴다. 세션 제외 건수와 window 제외 건수를 별도로 센다. 개인 이름·메모·영상 경로는 보고에 노출하지 않는다.
5. export는 임시 output 디렉터리에서 수행하고 성공 manifest를 마지막에 기록한다. strict 실패나 I/O 실패 후 남은 출력이 완성된 학습 데이터로 오인되지 않게 한다. 기존 output을 자동 덮어쓰지 않는다.
6. 제외 후 표본이 0개이거나 train/validation/test 중 비어 있는 split이 있으면 그 상태를 명시한다. 성공 메시지에 예제 수를 포함하고 학습 가능하다고 과장하지 않는다.

### 완료 기준

동일 root에 정상·미완료·복구·손상 fixture가 있어도 기본 모드는 정상 예제만 출력하고 제외 보고서를 남긴다. strict는 오류로 끝나며 완료 manifest를 만들지 않는다. 입력 원본의 해시가 바뀌지 않아야 한다.

## 7. F5 — 부분 반복과 검토 UI 복구 기능

### 실패 재현

start=155°, top=60°인 PILOT에서 170°→약125°→170°를 여러 번 반복한다. 목표 각도에 도달하지 않은 채 돌아오는 경우 현재 concentric 상태가 유지되어 리뷰 fixture에서는 6초 동안 attempt=0, 종료 후 attempt=1이 됐다.

### 수정 요구사항

1. 시작 자세를 이탈한 뒤 top 미도달 상태로 시작 구간에 다시 진입하면 부분 시도를 종료한다. hysteresis와 지속시간 조건으로 센서 떨림·준비 동작과 구분한다.
2. `partial_rom` 또는 `return_before_top` 등 사유로 invalid attempt를 기록하고 다음 시도를 위해 ready로 복귀한다. 추적 유실이 포함되면 unknown을 우선하고 근육 실패로 단정하지 않는다.
3. phase timeout은 보조 경로로 유지하되 여러 번의 되돌아온 시도를 하나로 합치지 않는다. 중지 시 진행 중 attempt는 마지막으로 한 번만 기록한다.
4. 부분 시도 invalid와 세트의 terminal technical_failure는 별개다. 유효 반복 수에 더하지 않되, 모든 invalid를 자동 한계로 확정하지 않는다. 종료 프로토콜에 따라 검토자가 terminal attempt를 선택한다.
5. 검토 UI에 **시도 추가·삭제·분할·병합**과 경계 조정을 제공한다. 읽기 전용 attempt_id를 사용자가 임의로 중복시키는 방식 대신 안정적인 신규 ID를 발급한다. 삭제·분할 관계와 기존 ID를 revision에 보존한다.
6. failure 선택 목록은 편집 결과와 동기화한다. 참조한 시도가 삭제되면 확정을 차단하고 재선택을 요구한다. split 후 terminal 참조를 임의 승계하지 않는다.
7. start/end 순서, 세트 밖 경계, 겹침, phases 경계/순서, 중복 ID, unknown 포함 여부를 append_review와 validator 양쪽에서 검증한다. 표 일부만 고쳐도 다른 검증 경로를 우회하지 못하게 한다.
8. 라벨은 수정된 effective review 전체에서 재생성하고 원본 repetitions.csv는 불변으로 보존한다. N과 k를 다시 계산하며 나중에 한 반동 반복을 기존 최대치에 섞지 않는다.

### 완료 기준

- 충분한 지속시간이 있는 부분 컬 3회는 서로 다른 invalid attempt 3개다.
- 정상 컬·중복 경계 jitter·추적 손실·중간 중지 테스트가 기존 동작을 유지한다.
- UI로 누락 시도를 추가하고 경계를 분할한 뒤 저장·재열기·라벨 export가 재현된다.
- 유효 15회+실패 1회 fixture에서 k=10/14/15의 잔여는 5/1/0이다.
- 부분 실패 1개를 추가했다고 세트가 자동 exact로 확정되지 않는다.

## 8. F6 — 객관적 독립 검토와 조정의 확정 조건

### 실패 재현

첫 검토를 objective_review=False로 저장한다. 다른 reviewer가 objective_review=True, adjudication=True로 두 번째 revision을 저장한다. 현재는 첫 검토의 객관적 검토 완료 여부를 확인하지 않아 confirmed가 생성된다.

### 수정 요구사항

1. 서로 다른 두 reviewer의 **objective_review=True인 완료된 평가**가 있어야 한다. 현재 검토자의 체크만으로 이전 검토를 완료 처리하지 않는다. 초안·미완료·automatic entry는 필요한 검토 수에 포함하지 않는다.
2. 단순히 직전 revision의 reviewer_id와 현재 문자열이 다르다는 조건을 독립 판정의 증거로 사용하지 않는다. assessment_id, reviewer_id, evidence/alignment version, source acquisition hash, base_revision, 검토 완료 시각을 기록한다.
3. UI에 독립 판정 모드와 조정 모드를 구분한다. 독립 판정은 원 자동 결과에서 시작하며 이전 사람 판정 내용을 보지 않는 흐름을 제공한다. 소규모 로컬 앱의 reviewer_id 입력만으로 신원을 보증한다고 주장하지 않는다.
4. 일치도는 두 독립 assessment를 대상으로 계산한다. 이전 판정을 그대로 로드한 뒤 reviewer_id만 바꿔 저장한 것을 독립 일치로 집계하지 않는다.
5. 불일치 조정은 비교한 두 assessment_id와 불일치 항목·해결 근거를 명시한다. 두 번째 유효 평가가 없는 상태에서 adjudication 체크만으로 confirmed로 전환하지 않는다.
6. 두 평가가 objective라고 해도 영상 동의·실제 근거 파일·참조 일관성·실패 시도·unknown·종료 조건 검증을 통과해야 한다. 미래 모델 결과나 EMG 피로도를 동작 정답 근거로 사용하지 않는다.
7. review_status와 censoring_status의 일관성을 강제한다. 기술적 실패가 확인된 confirmed만 exact다. 자발적·통증·장비 중단은 확정 검토하더라도 exact가 아니다. 정렬/경계/판정 근거 변경으로 confirmed를 해제하면 exact도 함께 해제한다.
8. 검토 저장은 expected_revision을 확인해 오래된 UI에서 새 판정을 덮는 것을 막는다. 원자적 revision 저장·manifest 갱신 실패를 복구할 수 있게 하고, 실패 후 labels_confirmed가 실제 기록과 다르게 남지 않게 한다.
9. 이전 형식의 human_review 기록은 보존해서 읽되, 새 독립 평가 요건을 만족한다고 임의 간주하지 않는다. 근거 부족 시 재검토 필요 상태로 보고한다.

### 완료 기준

objective=False 초안+True 조정은 provisional이다. 같은 reviewer의 두 평가도 provisional이다. 서로 다른 두 유효 독립 평가가 일치하거나, 적법한 조정을 거친 경우만 confirmed다. 자발적 중단은 언제나 remaining=null이다. stale revision·missing evidence·obsolete alignment·저장 실패 테스트가 확정을 차단한다.

## 9. 공통 구현·호환성 요구사항

- 원시 acquisition 스키마는 가능하면 유지하고 정렬·품질·review provenance를 버전별 파생 스키마에 추가한다. major 변경이 필요하면 reader·validator·migration 계약부터 문서화한다.
- v2 이두/상완요골근 데이터는 삼두로 재명명하지 않는다. 신규 이두/삼두 profile은 기존 헤더 검증을 유지한다.
- 기존 자동 라벨 파일과 새 정렬/검토 기반 파일의 의미를 구분한다. immutable 파일을 재생성해서 기존 해시에 조용히 맞추지 않는다.
- UI/validator/export가 서로 다른 자격 조건을 구현하지 않게 공통 eligibility 함수를 사용한다.
- source revision, alignment version, quality policy, protocol version, review revision, export 옵션을 export manifest에 남긴다.
- synthetic과 실제 데이터를 묵시적으로 혼합하지 않는다. 수정으로 생성한 테스트 fixture에는 synthetic을 명시한다.
- 모델 후보는 그대로 유지한다. 본 수정의 성공을 모델 정확도 개선이라고 표현하지 않는다.
- PyQt·MediaPipe·Windows 빌드 제약을 검증 없이 변경하지 않는다. UI 스레드에 추론·대량 파일 I/O를 추가하지 않는다.

## 10. 권장 테스트 구성

아래 파일명은 제안이며 기존 파일을 확장해도 된다. 구현을 그대로 복사하는 테스트 대신 실제 실패·경계·회귀를 검증한다.

| 테스트 영역 | 최소 사례 |
|---|---|
| `test_clock_alignment_and_availability.py` | 알려진 offset/drift/지연, mapping 불명, burst, epoch, 미래 데이터 배제 |
| `test_emg_window_quality.py` | 0.333Hz 희소 신호, 정상률, jitter, 큰 gap, clipping, mask, 경계 |
| `test_collection_watchdog.py` | 시작 무응답, 도중 무응답, malformed 지속, 회복, 종료 경합 |
| `test_export_session_isolation.py` | 정상+미완료+손상, 기본/strict, 빈 split, 원본 불변 |
| `test_partial_repetitions_and_review_edits.py` | 부분 3회, jitter, unknown, 추가/삭제/분할/병합, failure 참조 |
| `test_independent_review_confirmation.py` | 초안 우회, 동일 reviewer, 독립 평가, 조정, stale revision, 근거 변경 |
| 통합 시험 | 수집→정렬→품질→검토→export와 v2 reader 회귀 |

시간 제어에는 injectable monotonic clock을 사용한다. 테스트 속도를 위해 실제 수초씩 잠들지 않는다. 새 threshold는 테스트 이름과 fixture에서 그 의미를 설명한다.

예시 명령:

```bash
# 수정 전·후 동일 환경에서 실행
python -m pytest -q

# Linux headless UI 시험
QT_QPA_PLATFORM=offscreen python -m pytest -q

# 실제 제공 CLI에 맞게 신규 옵션 문서화
python scripts/validate_dataset.py <dataset-root>
python scripts/export_training_dataset.py --help
```

Windows에서는 기존 빌드 지침을 따라 EXE self-test도 실행한다. 장치가 없으면 mocked/synthetic 검증과 실장치 미검증을 구분한다. 검증 로그에 수치나 passed 개수를 예상으로 적지 않는다.

## 11. TODO — 실행 순서

- [ ] 현재 HEAD·작업 지침·baseline 테스트 확인, 기존 변경과 충돌 점검.
- [ ] F1~F6 실패 fixture를 작성하고 수정 전 실제 실패 결과 기록.
- [ ] 측정 시각/availability/mapping/quality/review의 공통 데이터 계약 확정.
- [ ] F3 watchdog과 장애 상태 처리 수정.
- [ ] F1 epoch별 정렬·가용 시점 구분과 공통 연결 경로 구현.
- [ ] F2 window 품질 검사·mask·학습 자격 조건 적용.
- [ ] F4 세션 격리·기본/strict export·제외 보고 구현.
- [ ] F5 부분 반복 상태 전이와 검토 편집 기능 구현.
- [ ] F6 독립 평가·조정·확정·revision 충돌 처리 구현.
- [ ] 기존·신규 시험과 end-to-end fixture 실행.
- [ ] README·스키마·수집/검토 안내·PROGRESS_REPORT 갱신.
- [ ] 가능 환경에서 Windows EXE self-test와 실장치 파일럿 실행, 불가 항목 기록.

F3를 먼저 적용해도 F1/F2 데이터 계약을 임의로 바꾸지 않는다. 각 기능 완료 후 관련 테스트를 실행하고, 공통 코드 변경 뒤 전체 회귀 시험을 실행한다.

## 12. 체크리스트 — 최종 완료 판정

- [ ] 알려진 지연 fixture에서 올바른 측정 시각으로 EMG·자세가 연결된다.
- [ ] 알 수 없는 동기 오차를 검증됨으로 표시하지 않는다.
- [ ] 미래 수신·추론·시간 보정 관측이 과거 예측 입력으로 들어가지 않는다.
- [ ] 심한 EMG 희소·gap·epoch 교차가 정상 학습 window로 통과하지 않는다.
- [ ] 첫 정상 샘플 이후에도 serial stall과 malformed 지속을 감지한다.
- [ ] 장치 오류 세트는 원본 보존·incomplete·잔여 exact 미확정 상태다.
- [ ] 미완료 세션이 있어도 정상 세션은 기본 export되고 제외 근거가 남는다.
- [ ] strict 실패 출력이 완성된 데이터로 오인되지 않는다.
- [ ] 여러 부분 시도가 각각 기록되며 검토 UI로 누락/경계를 복구할 수 있다.
- [ ] 편집 이후 terminal failure 참조·유효 반복·잔여 라벨이 일관된다.
- [ ] 객관적 독립 평가 두 건이 없으면 adjudication으로 확정을 우회할 수 없다.
- [ ] confirmed 해제 시 exact·labels_confirmed 상태도 일치한다.
- [ ] 기존 v2·원시 acquisition·영상·검토 이력이 보존된다.
- [ ] 실제 실행 명령·테스트 결과·검증 환경·미검증 부분을 보고했다.

## 13. 최종 제출과 중단 인계

제출: 수정 코드, 최소 재현/회귀 테스트, 변경 스키마·policy 문서, 합성 통합 예제, 변경 전/후 시험 결과, 사용자 영향 및 호환성 안내.

최종 보고에는 F1~F6별 재현 조건·원인·수정 위치·시험 결과를 표로 정리한다. 실제 장치 동기 품질과 Windows EXE는 실행한 경우에만 확인 완료로 쓴다. 커밋/PR은 현재 작업 환경의 지침과 사용자 승인 범위에 따른다.

중단 시 `PROGRESS_REPORT.md`에 현재 HEAD, 완료 ID, 남은 TODO, 실패 재현 명령, 실제 테스트 결과, 스키마/정렬/quality/review 버전, 다음 작업을 기록한다. 원본 참가자 데이터나 비밀정보를 넣지 않는다. 다음 작업자는 기존 완료 항목을 재구현하지 않고 재현 테스트부터 확인한다.
