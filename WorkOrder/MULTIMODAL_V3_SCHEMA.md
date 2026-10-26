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

시퀀스 결측은 값 0 + 같은 shape의 bool mask=False다. 실제 ADC 0은 mask=True다.
`index.csv`는 참조 ID와 예측 시각, split, target만 담으며 feature와 분리한다.
`remaining_valid_reps`는 exact일 때 N-k, 검열 자료는 null이고 초기 export에서 제외한다.
`next_attempt_failure`는 terminal failure가 바로 다음 시도인지에 대한 별도 target이다.
인적정보·중량 feature는 명시적 옵션이며 자유메모/이름/영상경로는 어떤 feature에도 없다.

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
| pose_age_ms | sample 수신시각 - pose 촬영측 수신시각, ms; 음수/허용 gap 초과 연결 금지 |
| elbow_angle_deg,trunk_tilt_deg,upperarm_delta_deg,pose_valid | 자세 각도 deg와 mask; 가림/결측 시 공백+False |
| phase | ready,concentric,top,eccentric,completed,unknown; 가림/결측은 unknown |
| attempt_id,attempt_validity | 반복 참조/valid,invalid,unknown; 반복 밖은 ID 공백+unknown |
| label_source,label_status,label_revision | mediapipe_pose/provisional/automatic; 별도 검토 export는 reviewed_mediapipe_pose 및 검토 revision |
| synthetic | 부모 세션의 bool; 모든 행에 명시 |

자동 파일은 사후 반복 경계에 따라 생성한 provisional 라벨이며 온라인 입력 feature가 아니다.
원본 samples/pose의 서로 다른 속도는 유지한다. 검토 export는 새 출력 파일이며 자동 파일을 수정하지 않는다.
