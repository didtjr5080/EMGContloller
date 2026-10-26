# v3.0.0 데이터 사전

데이터 스키마 3.0.0과 운동 프로토콜 0.1.0은 별도 버전이다. 기본 protocol status=PILOT.
CSV 공백/JSON null은 미입력·관측 불가이며 0은 실제 0이다. quality mask가 결측 이유를 나타낸다.
동의 없는 영상은 파일 자체가 없고, world 좌표 미제공은 null이다. CSV bool은 True/False다.

| 위치/필드 | 단위·허용값 | 결측/해석 |
|---|---|---|
| participant_id | `P-` + 영숫자 4자 이상 | 필수 익명 연결키; feature 제외 |
| participant.age/sex | 1–120세 / male,female,unspecified | unspecified=미응답 |
| height_cm, weight_kg | 50–250cm / 10–350kg | 체중만 선택 null |
| dominant_arm | left/right/both/unspecified | 미응답=unspecified; 측정 팔과 별도 |
| exercise_sessions_per_week, strength_sessions_per_week | 주당 0–21회 | 근력운동만 선택 null |
| exercise_minutes_per_week | 주당 정수 0분 이상 | null=미입력, 0=운동 시간 0 |
| strength_training_months | 정수 0개월 이상 | null=미입력 |
| questionnaire_period, strength_exercise_definition | 모델 기본 정의 문구 | 설문 기준/종목 정의; 입력 feature 아님 |
| days_since_last_exercise | 0일 이상 | 기존 v2 항목 유지; 방문 항목이 현재 상태 |
| visit_id, session_id | 비어 있지 않은 연결키 | 세션당 한 세트, visit_id로 방문 연결 |
| visit.hours_since_exercise/upper_body_exercise | 0시간 이상 | null=미입력; 세션별 스냅샷 |
| visit.fatigue_score/pain_score | 정수 0–10 | null=미입력; 0=실제 자기보고 0 |
| start_host_ns/start_time_utc | host monotonic ns / UTC ISO8601 | 필수 시작 기준 |
| synthetic | boolean | 필수; 모든 하위 스트림/출력의 provenance |
| consent.research/pose_coordinates | boolean | 둘 다 true여야 수집 가능 |
| consent.video_storage/access/export | boolean | access/export에는 storage가 필요; false는 거절/미동의 |
| channels.sensor_id/channel_id | sensor1/2, s1/2_env/raw | 고정 slot mapping; 필수 |
| channels.muscle/side/signal/gpio | biceps,triceps / left,right / RAW,ENV / 33,34,32,35 | v2 profile만 brachioradialis; 결측 자동 추정 금지 |
| electrode_placement/skin_prepared/sensor_settings | 위치 기록 / bool / 설정 기록 | 실제 v3 수집은 위치·피부준비 필수; RAW 대역 미검증 명시 |
| camera/pose | API·모델해시·시각출처·원본좌표계·지표버전 | synthetic 모델해시는 null; 실제 파일 불명 시 시작 불가 |
| protocol.* | 각도 deg, 시간 s/ns, confidence 0–1 | 허용범위와 상호관계는 PilotProtocol 모델 검증; 후보값은 승인 표준 아님 |

| 스트림/열 | 단위·허용값 | 결측/검증 |
|---|---|---|
| samples.sample_index | 0부터 연속 정수 | 필수 |
| epoch_id | 0 이상 정수 | reset/reboot 추정마다 증가 |
| device_time_us | uint32 us | 원시 micros |
| unwrapped_time_us | 0 이상 us | epoch 안에서 비감소 |
| host_receive_ns | 0 이상 host ns | 수신 시각, 비감소 |
| s1_env/s1_raw/s2_env/s2_raw | 정수 ADC 0–4095 | 필수; s2 의미는 metadata profile; mV 아님 |
| pose_landmarks.frame_id/landmark_id | frame 참조 / 0–32 | 전체 제공 landmark 보존 |
| capture_host_ns/infer_host_ns | host ns | 추론완료 >= 촬영측 수신시각 |
| x,y,z | MediaPipe normalized 좌표 | 영상 밖 좌표 가능; z는 임상 거리 아님 |
| world_x/y/z | MediaPipe world 좌표 | 미제공=null; 실제 측량 좌표 아님 |
| visibility/presence | 0–1 confidence | API 미제공이면 null; 신뢰도 미달은 metrics mask |
| validity | detected/synthetic | 검출/모의 provenance; 미검출 프레임은 metrics tracking_loss |
| pose_metrics.frame_id/capture_host_ns/infer_host_ns/arm | 참조 / host ns / host ns / left,right | frame timestamp 일치 필수 |
| elbow_angle_deg/trunk_tilt_deg/upperarm_delta_deg | deg | 추적 불가·퇴화 시 null, quality_mask로 이유 |
| quality_mask | ok/tracking_loss/degenerate | 추적 유실은 반복 unknown으로 전파 |
| frame_timestamps.frame_id/capture_host_ns | 프레임 ID / host ns | ID 중복 불가, 시각 증가 |
| timestamp_source | opencv_read_completion/synthetic_host | 노출시각으로 해석 금지 |
| segment/segment_frame | 파일명 / segment 내 정수 frame index | 영상 미저장 시 공백 |
| saved/inference_submitted | boolean | 영상 저장과 추론 생략을 별도 기록 |
| sets.set_id/arm/set_number/exercise | 연결키 / left,right / 1 이상 / unilateral_dumbbell_curl | 필수 |
| load_kg/rest_before_s/target_repetitions | 덤벨 한 개 kg >=0 / s >=0 / 정수 >=0 | 휴식·계획만 선택 null; 계획은 N 아님 |
| dumbbell_count | 사용하는 덤벨 개수, 정수 >=1 | 새 sets.csv와 review snapshot에 저장; 없는 기존 기록은 1로 읽음 |
| start_ns/end_ns | host ns | end>=start; 시도는 세트 경계 내 |
| termination_reason | technical_failure,voluntary_stop,pain_discomfort,equipment_failure,tracking_failure,protocol_deviation,planned_stop,other | 수집 종료 시 필수, raw와 review revision 분리 |
| failure_attempt_id/failure_attempt_observed | attempt 참조 / true,false,null | null=확인 불가; false=실패 시도 없음; ID 있으면 true |
| review_status/objective_review | provisional,confirmed / boolean | 파일 완료와 라벨 확정은 별도 |
| observed_valid_count/censoring_status | 정수 >=0 / unreviewed,right_censored,exact,unknown | 원시 관찰값과 검열 구분; exact는 검토된 technical failure만 |
| repetitions.attempt_id/set_id | 시도키 / set 참조 | 중복·겹치는 시도 금지 |
| start_ns/end_ns/phases | host ns / host ns / phase→host ns JSON | 시도 경계 내 phase; partial/timeout도 보존 |
| validity/reasons | valid,invalid,unknown / 사유 배열 JSON | 추적 유실·ROM·tempo·trunk·upperarm·partial·timeout 등 |
| rom_deg/provisional | deg / boolean | 계산 불가=null; 자동 결과는 true |
| events.host_ns/sample_index/event_type/detail | host ns / sample 참조 / 종류 / 내용 | sample 없음=null; detail은 export 제외 |
| annotations.* | revision/previous_revision/reviewer_id/UTC ns/reason/sets/attempts | append-only; 원본 불변; reason은 export 제외 |
| agreement_report | paired_attempts,agreement,kappa,boundary_mae_ms,angle_mae_deg | 분모/정답 없으면 null; synthetic 일치는 실제 신뢰도 아님 |
| sync.epochs.* | offset ns,drift ppm,residual ns,방법·상태 | 데이터 부족=null; 잔차는 물리적 동기 정확도 아님 |
| quality.* | 관찰 sample/frame수,실측 Hz/fps,drop/clip/queue/regression 추정 | 원본 카메라 drop·physical sync error 미측정=null; rate는 최근 10000 관측값 |
| completion_manifest.* | 파일 존재·행수·bytes·SHA256·playable·status | 마지막 기록; 누락/오류/part/복구는 incomplete |

기본 수집 UI는 1회 측정 전용이다. 이름은 participants_private.csv에만 저장하고
participant ID·visit ID·세트 번호는 내부 참조로 유지한다(화면 입력/유지 없음).
피부/복장 확인 체크를 제거했으므로 새 UI 수집은 preparation_confirmation=not_confirmed,
channel.skin_prepared=False, clothing_confirmed=False로 기록한다. False를 준비 완료로 해석하지 않는다.

시퀀스 결측은 값 0 + 같은 shape의 bool mask=False다. ADC 0/4095는 clipping으로 mask=False다.
불규칙 관측의 실제 시각과 gap은 별도로 보존한다. mask=True가 연속 수집의 증거는 아니다.
`index.csv`는 참조 ID와 예측 시각, split, target만 담으며 feature와 분리한다.
`remaining_valid_reps`는 exact일 때 N-k, 검열 자료는 null이고 초기 export에서 제외한다.
`next_attempt_failure`는 terminal failure가 바로 다음 시도인지에 대한 별도 target이다.
인적정보·중량 feature는 명시적 옵션이며 자유메모/이름/영상경로는 어떤 feature에도 없다.
--include-load를 선택하면 load_kg(한 개당 무게)와 dumbbell_count를 함께 내보낸다.
새 metadata.equipment에도 load_kg_per_dumbbell과 dumbbell_count를 저장한다.
한 개 무게를 개수로 곱하여 기존 load_kg 의미를 바꾸지 않는다.

식별정보나 실제 수집 자료는 저장소에 추가하지 않는다. models/datasets/video는 gitignore 대상이다.

## EMG + MediaPipe 통합 라벨 CSV (추가 파생 파일)

새 수집의 `metadata.labeling.sample_labels_file=labeled_samples.csv`가 파일 존재를 선언한다.
기존 v3 세션에 이 선언이 없으면 필수 파일로 요구하지 않는다. 선언된 파일은 완료 manifest의
SHA-256·행수와 함께 검사하며, 각 행의 EMG 값·시각은 원본 samples와 같아야 한다.

| 열 | 의미/단위 |
|---|---|
| sample_index,epoch_id,device_time_us,unwrapped_time_us,host_receive_ns | 원본 EMG 참조/장치 us/host ns |
| biceps_env_adc,biceps_raw_adc,triceps_env_adc,triceps_raw_adc | 원본 s1/s2에 대응하는 ADC 정수; 명시적 이두·삼두 profile에서만 생성 |
| set_id,pose_frame_id,pose_capture_host_ns,pose_infer_host_ns | 세트/자세 프레임 참조와 host ns; 연결 불가 시 pose 필드는 공백 |
| pose_age_ms | measurement_host_ns - pose 촬영측 수신시각, ms; 음수/허용 gap 초과 연결 금지 |
| elbow_angle_deg,trunk_tilt_deg,upperarm_delta_deg,pose_valid | 자세 각도 deg와 mask; 가림/결측 시 공백+False |
| phase | ready,concentric,top,eccentric,completed,unknown; 가림/결측은 unknown |
| attempt_id,attempt_validity | 반복 참조/valid,invalid,unknown; 반복 밖은 ID 공백+unknown |
| label_source,label_status,label_revision | mediapipe_pose/provisional/automatic; 별도 검토 export는 reviewed_mediapipe_pose 및 검토 revision |
| synthetic | 부모 세션의 bool; 모든 행에 명시 |

자동 파일은 사후 반복 경계에 따라 생성한 provisional 라벨이며 온라인 입력 feature가 아니다.
원본 samples/pose의 서로 다른 속도는 유지한다. 검토 export는 새 출력 파일이며 자동 파일을 수정하지 않는다.

## 코드 리뷰 수정 계약 (review-fixes-1)

부모 스키마는 3.0.0, v2 reader는 유지한다. 새로운 필드는 파생 파일과 버전별 계약에 추가한다.
기존 acquisition과 자동 라벨은 제자리 변환하지 않는다. 기존 reviewed 기록은 읽을 수 있지만
새 독립 평가 근거가 없는 기록은 provisional이며 exact 학습 대상으로 승계하지 않는다.

| 계약 | 저장 필드와 의미 |
|---|---|
| alignment-1 | sync.epochs[epoch]의 mapping 목록: mapping_version, method, status, offset_ns, drift_ppm, uncertainty_ns, valid_from/to_device_us, available_host_ns, fit_scope, observed intervals |
| physical time | measurement_host_ns = offset_ns + (1+drift_ppm/1e6) × unwrapped_time_us × 1000; 다른 epoch mapping 사용 금지 |
| alignment status | aligned 또는 alignment_unverified. reference_event + reference_event_ids 또는 synthetic 세션의 synthetic_reference만 검증 경로. 허용 uncertainty 초과도 미검증 |
| receive fit | software_receive_linear_fit의 잔차와 latency bias/물리 오차는 별개. uncertainty/latency_bias/physical_sync_error는 미확인 시 null |
| availability | prediction_capture_ns는 반복 종료 촬영 경계, decision_host_ns는 추론 완료와 debounce를 기다린 결정 시각. 지연 상한은 품질 정책에 명시 |
| causal export | measurement time ≤ prediction_capture_ns, host_receive_ns/infer_host_ns 및 causal mapping.available_host_ns ≤ decision_host_ns. posthoc fit은 예측 입력에서 제외 |
| derived labels | measurement_host_ns, alignment_status, alignment_uncertainty_ns, mapping_version 추가. 미검증 기본값은 pose/시도 unknown이며 label_status=alignment_unverified |
| alignment replacement | alignment-{fingerprint}.json 불변 파일 + alignment_current.json 포인터. sync.json 보존. 변경 시 근거 fingerprint가 달라져 기존 확정 해제 |
| watchdog-1 | 시작 5초, 유효 수신 정체 3초, grace 0.5초, 종료 대기 5초. 유효 샘플만 갱신; serial/camera/pose 공통 정책 |
| fault | events/quality에 code, detected_host_ns, last_valid_sample_host_ns. equipment_failure와 incomplete로 보존. motion_end_host_ns와 acquisition_end_host_ns 분리, 추가 수신 유예는 현재 0 |
| review-2 | assessment_id, reviewer_id, mode, completed_at_utc_ns, base_revision, evidence, previous_revision. evidence는 acquisition hash와 alignment/protocol/review 버전 |
| independent | base_revision=acquisition, objective_review=True, 완료 시각이 있는 서로 다른 검토자의 두 평가. 독립 UI는 원 자동 판정부터 시작 |
| adjudication | 두 confirmation_assessment_ids, 모든 resolved_disagreements, reason 필수. 서로 다른 평가를 선택하며 단순 reviewer ID 변경으로 이전 초안 승격 불가 |
| CAS / recovery | expected_revision 불일치 저장 거절. review_transaction.json이 있으면 provisional. journal .next와 전/후 해시로 복구하며 manifest는 잠정 미확정 후 마지막 갱신 |
| attempt edits | ID 읽기 전용, 새 시도는 UUID 기반 ID. edit_operations에 source_ids/created_ids/previous 기록. terminal 삭제·분할 시 재선택 필수 |

### 품질 정책 emg-quality-1

PILOT 공학 후보값이며 연구 검증된 표준이 아니다. metadata.quality_policy 또는 CLI
--quality-policy JSON으로 설정하고 export manifest에 실제 policy와 fingerprint를 남긴다.
기본값: 예상 500Hz, 허용 450~550Hz, 시간 합집합 커버리지 ≥0.9, 최대 gap 20ms,
ADC 0/4095 비율 ≤0.05, clock uncertainty ≤50ms, decision 지연 ≤500ms, epoch 교차 금지.

window_quality.json은 expected/observed_samples, unique_timestamps, actual_rate_hz,
coverage_ratio, max_gap_ns(양 경계 포함), clipping_ratio, epoch_count, alignment_status와
reasons를 기록한다. 중복·burst 관측 개수만으로 커버리지를 늘리지 않는다.
부분 초기 window는 세트 시작으로 잘라 해당 실제 길이를 분모로 계산한다.
심한 gap window는 기본 제외하며, 보간이나 epoch를 가로지르는 이어 붙이기는 하지 않는다.

sequences/*.npz는 values/mask 외 measurement_host_ns, host_receive_ns, gap_before_ns,
epoch_id를 보존한다. host_ns는 호환용 측정시각 별칭이다. index의 prediction_host_ns는
prediction_capture_ns의 호환 별칭이다. 이용 가능한 과거 pose로만 동작 특징을 재계산한다.

validate_session()은 기존 integrity 오류 목록 API다. inspect_session()은 integrity_errors와
quality를 별도로 반환한다. 무결성 통과만으로 학습 적격을 의미하지 않는다.
기본 export는 세션을 격리하고 exclusion_report.json에 세션/창/세트 집계를 분리한다.
strict 실패나 I/O 실패는 최종 출력과 complete manifest를 공개하지 않는다.
빈 split/0예제는 명시하며 training_ready=False다. 진단 미검증 허용 자료도 항상 training_ready=False다.
