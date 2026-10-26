# EMGContloller 확장 작업 지시서

작성일: 2026-10-26 (한국 시간)  
대상: https://github.com/didtjr5080/EMGContloller  
검토 커밋: `58f8d4ab5135e2251b794cdeba54bb60cf4121db`  
산출 목적: 기존 수집기를 이두·삼두 EMG와 MediaPipe 자세, 반복 판정 및 수행 한계 라벨을 함께 기록하는 연구용 수집기로 확장한다.

> 이 문서는 구현을 요청하는 지시서다. 신규 기능을 이미 구현·시험했다는 보고서가 아니다. 실제 작업 시작 시 현재 HEAD와 AGENTS.md를 확인하고 차이를 먼저 기록하라. 저장소 코드를 이 문서의 스냅샷으로 되돌리지 마라.

## 1. 목표와 범위

목표는 **표준화한 덤벨 컬 조건에서 기술적 실패까지 남은 유효 반복 수**를 학습할 수 있는 데이터셋을 만드는 것이다. 유효 반복은 사전에 정한 동작 기준을 통과한 반복이며, 근비대 맥락의 효과적인 반복이라는 뜻이 아니다. 절대적인 생리학적 한계나 피로도 %를 정답으로 주장하지 않는다.

이번 작업은 수집·동기화·검토·라벨·학습 입력 내보내기까지다. 최종 예측 모델 선정이나 실제 참가자 데이터 수집은 별도다. Ridge, SVR, Random Forest, XGBoost, 1D-CNN, LSTM/GRU, CNN-LSTM/DeepConvLSTM 변형, TCN을 **후보**로 남긴다. HAR은 특정 모델명이 아니라 참고할 시계열 구성 접근이다.

초기 기본 프로토콜은 한쪽 팔의 이두·삼두를 센서 2개로 측정한다. 양팔 동시 이두·삼두에는 추가 채널이 필요하므로 현재 하드웨어로 지원한다고 표시하지 않는다. 팔별 세트는 별도 식별하고 부착 변경을 기록한다.

## 2. 실제 저장소에서 확인한 상태와 수정 근거

| 경로 | 확인한 상태 | 변경 방향 |
|---|---|---|
| `README.md`, `config.py`, 펌웨어 | 이두·상완요골근 센서 2개, RAW/ENV 총 4 ADC, 500 Hz, 460800 baud | 새 수집은 이두·삼두 프로파일; 과거 상완요골근 의미 보존 |
| `models.py` | 나이·성별·키·체중·운동 횟수·최근 운동 경과일 존재 | 기존 항목 재사용, 세션별 상태 스냅샷과 운동 경력 추가 |
| `SampleRecord`, `parser.py` | `brachio_*` 명칭 및 5열 시리얼 고정 | 명시적인 프로토콜/채널 매핑과 버전별 판독 |
| `storage/session_writer.py` | samples/events `.part` 기록, finalize 시 flush/fsync/rename | 다중 스트림 완료 manifest와 장애 복구 확장 |
| `ui/participant_form.py` | 이름 필수, 동의 확인, 기본 인적 정보 입력 | 익명 ID 중심 등록과 동의 종류 구분 |
| `pyproject.toml` | PyQt6·pyqtgraph·pyserial·pydantic, Python >=3.11 | 기존 데스크톱 UI 유지, MediaPipe/OpenCV 호환 검증 후 추가 |
| 저장소 트리 | 카메라·자세·반복 판정 전용 모듈 없음 | 독립 모듈 추가 |

위 항목은 해당 커밋 파일을 읽어 확인했다. README의 시험·하드웨어 검증 설명은 저장소의 기록이며 이번 문서 작성 중 재실행한 결과가 아니다. 기존 UI와 로거를 Flask로 전면 재작성하지 않는다.

## 3. 구현 전 실패 사례를 먼저 고정

기존 데이터를 훼손하지 않는 임시 fixture로 아래 사례를 테스트하라. 미구현 요구사항과 기존 결함을 구분하여 초기 결과를 남긴다.

1. 동일한 센서 2번 숫자열을 읽어도 기존 프로파일은 상완요골근, 신규 프로파일은 삼두근이어야 한다. 프로파일 없는 데이터가 자동으로 삼두근이 되면 실패다.
2. 15회 성공 후 자발적 중단한 세트는 `remaining_valid_reps=null`이어야 한다. 0이면 실패다.
3. EMG 500 Hz, 영상 약 30 fps에서 같은 행 번호끼리 결합하면 시각이 어긋나는 fixture를 만든다. 시간 기반 결합만 통과해야 한다.
4. 팔 가림·좌표 결측 구간은 `unknown`이어야 한다. 이를 실패 반복으로 확정하면 실패다.
5. 두 겹치는 window가 서로 다른 split으로 나뉘거나, 10회 시점 입력에 11회 이후 자료가 섞이면 실패다.
6. 세트 종료 직전 프로세스 중단으로 영상만 미완료인 경우, samples가 존재하더라도 전체 세트를 정상 완료로 선언하면 실패다.

## 4. 수집 항목과 데이터 사전

필드마다 단위·허용값·결측 사유를 문서화한다. 미입력과 실제 0을 구분한다. 특히 기존 폼이 0분을 미입력으로 바꾸는 부분을 수정한다.

| 단위 | 필수 또는 기록 대상 | 비고 |
|---|---|---|
| 참가자 | participant_id, 나이(세), 성별(미응답 포함), 키(cm), 체중(kg), 주사용 팔 | 이름은 선택적 별도 private 파일; 학습에는 제외 |
| 운동 이력 | 주당 운동 횟수, 주당 근력운동 횟수, 총 운동 시간(분), 근력운동 경력(개월), 설문 기준 기간 | 주당 기준을 UI에 명시하고 종목 정의도 저장 |
| 방문/세션 | visit_id, session_id, 날짜, 최근 전체 운동 및 상지운동 후 경과시간, 피로·통증 자기보고 | 시간에 따라 변하는 값은 참가자 전역값만 덮어쓰지 말고 세션에 저장 |
| 세트 | set_id, arm, set_number, exercise, load_kg, 직전 세트 후 휴식(초), 목표 템포·휴식 규칙 | 중량은 덤벨 한 개 기준; 계획 반복 수와 실제 한계 분리 |
| 채널 | sensor_id, channel_id, muscle, side, RAW/ENV 구분, GPIO, 전극 위치, 피부 준비, 센서 설정 | 이두·삼두 부착 위치는 연구 프로토콜에 맞춰 기록 |
| EMG | device epoch, 원시/unwrap 장치 시각, host 수신 시각, sample_index, RAW/ENV ADC | ADC를 검증 없이 mV로 변환하지 않음 |
| 영상/자세 | frame_id, 촬영 시각, 추론 시각, landmarks, visibility/presence(제공 시), 추적 상태 | 촬영 시각과 추론 완료 시각 분리 |
| 파생 동작 | 팔꿈치 각도, 몸통 기울기, 상완 방향 변화, 반복 시간, ROM | 계산 방식·단위·좌표계를 버전 관리 |
| 반복 시도 | attempt_id, 시간 경계, phase, valid/invalid/unknown, 사유 | 실패 시도도 별도 보존 |
| 종료/검토 | 종료 사유, 실패 시도 ID, 마지막 유효 반복, 판정자·수정 이력 | 자동 결과와 검토 결과를 분리 |
| 품질 | 실측 샘플링률·fps, 결측·클리핑·큐 초과·추적 손실·동기화 오차 | 측정하지 않은 값을 0으로 꾸미지 않음 |

동의: 연구 참여, 판정용 영상 저장, 영상 접근·내보내기 허용을 구분한다. 영상 미동의 시 자세 좌표 수집 여부도 설명하고, 다른 객관적 검토 수단이 없으면 검토 가능한 한계 라벨 상태로 확정하지 않는다. 원본 영상은 식별 가능 자료로 취급한다.

## 5. 프로토콜·채널 의미와 하위 호환

기존 핀은 이두 ENV 33/RAW 34, 두 번째 센서 ENV 32/RAW 35다. 센서 위치를 삼두로 바꾸더라도 핀을 임의 변경할 필요는 없다. 실제 배선과 장치 설정은 시작 전 확인한다.

- 기존 v2: `time_us,biceps_env,biceps_raw,brachio_env,brachio_raw`를 기존 의미로 읽는다.
- 신규 프로파일 예시: `time_us,biceps_env,biceps_raw,triceps_env,triceps_raw`. 신규 펌웨어 파일 또는 명시적 프로파일을 추가하고 기존 reference를 보존한다.
- 권장 내부 모델은 센서 슬롯과 채널 매핑으로 근육 의미를 분리한다. CSV가 wide 형식이어도 metadata의 매핑을 필수로 한다.
- 앱 선택 프로파일과 장치 헤더가 다르면 시작을 차단한다. 기존 헤더를 신규 매핑으로 사용하는 명시적 legacy 모드는 운영자가 실제 부착을 확인한 기록 없이는 허용하지 않는다.
- 신규 데이터 스키마는 major version을 올린다(예: 3.0.0). 프로토콜 버전과 데이터 스키마 버전은 별도다. v2 reader/validator/viewer는 보존한다.
- 기존 파일은 제자리 rename/migration하지 않는다. 변환이 필요하면 별도 출력과 provenance를 남긴다. 근육이 불명확한 과거 데이터는 unknown이다.
- v1 지원 여부는 별도 명시하고 지원하지 않는 버전에는 이해 가능한 오류를 낸다.

500 Hz는 기존 설정이며 광대역 RAW EMG 주파수 특징의 적합성을 보장하지 않는다. 센서 RAW 대역·아날로그 anti-alias·실측률을 확인하고, Nyquist를 넘는 필터 대역을 설정하지 않는다. ENV에서 MDF를 계산하지 않는다. 현 하드웨어의 대역 제한이 확인되지 않으면 MDF/MNF의 타당성을 미검증으로 표시한다. 샘플링 변경은 대역·ADC·직렬 전송 여유를 검증하는 별도 프로파일로 한다.

## 6. MediaPipe 수집과 시간 동기화

MediaPipe Pose를 사용한다. 다른 추적기로 교체하지 않는다. 설치 가능한 정확한 버전·모델 파일·해시·API·Windows Python 조합을 검증해 고정한다. 모델 파일 다운로드가 필요하면 경로와 실패 메시지를 제공한다. 단일 팔 테스트에 적절한 카메라 구도를 파일럿으로 정한다.

1. 카메라 capture와 pose inference, serial acquisition, writer를 독립 worker로 나눈다. UI 스레드에서 추론·동영상 인코딩·동기 flush를 실행하지 않는다.
2. 공통 host `monotonic_ns`와 UTC 시작 기준을 기록한다. EMG에는 수신 시각, 영상에는 가능한 촬영 시각과 그 시각의 출처를 저장한다. OpenCV read 시각만 가능하면 노출 시각으로 과장하지 않는다.
3. 장치 `micros()`의 rollover와 재부팅을 구분하고 재부팅마다 epoch_id를 새로 만든다. epoch별 장치-호스트 시간 매핑의 offset·drift·방법·잔차를 기록한다. 일괄 수신으로 생기는 지연을 무시하지 않는다.
4. 시작·종료의 공동 관측 가능한 동기 이벤트를 설계한다. 하드웨어 공통 trigger가 없으면 software-only 추정이라고 표시하고 실제 오차를 파일럿에서 측정한다. 목표 허용 오차는 protocol 설정이며 검증 전 달성했다고 표시하지 않는다.
5. 프레임 드롭을 고려해 frame_timestamps.csv를 저장한다. fps×frame 번호만으로 시간을 복원하지 않는다. 추론 생략 프레임과 영상 저장 프레임을 구별한다.
6. EMG와 pose는 원래 속도로 각각 저장한다. 정렬한 파생 데이터에 interpolation·nearest 방식, 최대 gap, mask를 기록한다. 허용 gap을 넘는 구간은 보간하지 않는다.
7. 양측 어깨·팔꿈치·손목·엉덩이를 포함한 Pose landmarks를 저장한다. 가능하면 전체 landmark를 보존하고 normalized/world 좌표를 구분한다. 좌우 미러링은 표시와 원본 좌표를 분리한다.
8. 화면 비율을 반영해 각도를 계산한다. world 좌표는 선택한 API 의미를 따르고 검증 없이 임상적 3D 측정값으로 취급하지 않는다. 2D 측면 구도의 한계와 가림을 표시한다.
9. 각 worker 큐는 유계로 한다. 표시·추론 프레임 생략과 원본 유실을 구분해 카운트한다. EMG 저장 큐 overflow는 명시적 품질 실패 이벤트다.

## 7. 유효 반복과 기술적 실패 판정

운동 프로토콜 파일에 시작/종료 각도, 최소 ROM, 몸통 반동·상완 이동 허용치, 템포 범위, phase timeout, confidence 기준, 연속 위반 허용시간, 종료 규칙을 저장한다. 구체적 수치는 파일럿과 교수님 검토로 확정할 값이며 임의 수치를 객관적 표준이라고 하드코딩하지 않는다. 미승인 프로토콜은 PILOT로만 수집한다.

- 상태: ready → concentric → top → eccentric → completed. partial attempt와 timeout도 기록한다. 각도 경계에는 hysteresis/debounce를 둬 중복 카운트를 막는다.
- 통과/미달/판정불가를 구분한다. 추적 손실은 동작 실패의 증거가 아니다.
- 부정확한 한 번의 자세나 준비 동작을 자동으로 수행 한계로 확정하지 않는다. 실제 시도 여부, 규칙 위반 지속 및 종료 규칙을 검토한다.
- 최초 프로토콜상 기술적 실패로 세트가 끝난 뒤 반동 반복을 추가하더라도 원 세트 최대치에 더하지 않는다. 긴 휴식·중량 변경·보조자 개입은 protocol deviation 또는 새 세트로 분리한다.
- EMG 피로 특징이나 AI 예측을 정답 판정 근거로 사용하지 않는다.
- 자동 판정은 provisional이다. 동기화된 영상·곡선·각도에서 검토자가 확정하고, 파일럿에서는 두 사람이 독립 판정 후 불일치를 조정한다. 일치율과 가능하면 kappa, 각도·반복 경계 오차를 보고한다.
- 복장은 위팔 앞뒤 전극을 가리지 않고 조이지 않는 민소매 또는 충분한 노출이 가능한 반팔을 기본으로 안내한다. 따뜻한 실내에서 확인하고, 소매·케이블로 ROM이 제한되면 clothing_interference로 기록한다. 피로성 실패 라벨로 바꾸지 않는다.

## 8. 세트 종료와 잔여 횟수 라벨

종료 사유 enum: `technical_failure`, `voluntary_stop`, `pain_discomfort`, `equipment_failure`, `tracking_failure`, `protocol_deviation`, `planned_stop`, `other`.

정확한 잔여 횟수는 **검토 완료된 기술적 실패 세트**에서만 생성한다. N은 종료 규칙에 따라 확인한 총 유효 반복 수, k는 예측 시점까지 완료한 유효 반복 수다.

`remaining_valid_reps = N - k`  
`estimated_total_valid_reps = k + predicted_remaining_valid_reps`

| 기록 | N 확정 | 10회 완료 직후 라벨 |
|---|---|---|
| 15회 유효 후 16번째 실패 시도, 검토 완료 | 15 | 5 |
| 15회 유효 후 자발적 중단 | null | null |
| 15회 유효 후 통증/센서 문제 종료 | null | null |
| 추적 유실로 실패 여부 확인 불가 | null | null |

자발적 중단에서는 관찰한 유효 횟수가 수행 능력의 하한이라는 사실만 저장한다. `censoring_status`와 `observed_valid_count`를 보존하되 운동 생리학적 최대치가 확인됐다고 해석하지 않는다. 초기 exact regression export에서 제외한다.

기본 예측 시점은 각 유효 반복 완료 직후로 정한다. 실패 시도 자체를 포함한 입력으로 그 직전의 잔여 횟수를 예측하지 않는다. 세트 완료 상태와 라벨 확정 상태는 별도이며 recovered/complete 파일만으로 라벨을 자동 확정하지 않는다. `next_attempt_failure`와 `remaining_valid_reps<=1`은 같은 라벨이 아니므로 별도 정의와 검증을 둔다.

## 9. 저장 구조와 최소 스키마

기존 participants/sessions와 v2 판독은 유지하고 v3 세션에 아래를 추가한다. 한 session은 하나의 방문 기록 또는 기존 세션 의미를 유지하되, 여러 set_id를 명확히 연결한다. 이 관계를 문서와 validator에서 고정한다.

| 파일 | 주요 열/내용 |
|---|---|
| `metadata.json` | schema, protocol, participant/visit/session 연결, channels, 환경·장치·동의·복장·카메라 설정 스냅샷 |
| `samples.csv` | sample_index, epoch_id, device_time_us, unwrapped_time, host_receive_ns, 채널 ADC |
| `pose_landmarks.csv` | frame_id, landmark_id, capture_host_ns, infer_host_ns, normalized xyz, world xyz(가능 시), visibility/presence, validity |
| `pose_metrics.csv` | frame_id, arm, elbow_angle_deg, trunk_tilt_deg, upperarm_delta_deg, quality mask |
| `frame_timestamps.csv` | frame_id, 저장 영상 segment/frame 연결, timestamp, dropped/inferred 여부 |
| `video/` | 동의 시 원본 판정 영상, 분할 segment와 완료 여부 |
| `sets.csv` | set_id, 시간 경계, 중량·팔·휴식·템포, 종료 사유, 실패 attempt, 검토 상태 |
| `repetitions.csv` | attempt_id, set_id, start/end/phase 경계, valid 상태, 사유, 누적 valid_count |
| `annotations.jsonl` | 자동 판정과 검토 revision, reviewer_id, 수정시각, 이전 revision, 이유 |
| `events.csv` | 기존 이벤트와 동기·프로토콜 변경·중단 이벤트; sample 없을 때 참조는 null 허용 |
| `sync.json` | epoch별 시간 매핑, 동기 이벤트, 오차·지연 추정과 방법 |
| `quality.json` | stream별 실측률·drop·gap·queue·동기 품질과 검증 가능 상태 |
| `completion_manifest.json` | 파일별 존재·행수·해시·완료/복구 상태, 세션 전체 상태 |

각 stream은 `.part` 또는 journal로 기록하고 닫힌 파일을 순차 finalize한 뒤 manifest를 마지막에 atomic replace한다. 여러 파일 rename 전체가 원자적이라고 주장하지 않는다. 부분 성공·디스크 부족·카메라 해제·비정상 종료에서 기존 파일을 덮어쓰지 않고 복구한다. 영상 segment는 재생 가능 여부를 별도 검증하며 텍스트 파일 복구만으로 복구 완료라고 하지 않는다.

비식별 export는 allowlist 방식이다. 이름·private 파일·원본 영상·영상 경로·식별 가능 자유메모는 기본 제외한다. 자세 좌표도 연구 데이터로 취급한다. 실제 참가자 데이터·영상·로컬 식별정보를 Git에 추가하지 않는다.

## 10. UI 요구사항

기존 PyQt6 창에서 다음 흐름을 구현한다.

1. 참가자 선택/등록 → 방문 상태 입력 → 이두·삼두 채널과 부착 확인.
2. 카메라·시리얼 미리보기 → 프로토콜 선택 → 복장/가동범위/추적/동기 품질 점검.
3. 세트 준비(팔·중량·휴식 확인) → 기록 시작 → EMG·카메라·각도·유효/무효/불명 시도 표시.
4. 종료 버튼에서 종료 사유와 실패 시도 유무를 필수 기록. 통증 중단 등은 즉시 기록 중지하고 사유를 후속 입력 가능하게 한다.
5. 검토 화면에서 영상·EMG·각도 타임라인을 같이 탐색하고 경계·유효성·종료 판정을 수정.
6. 검토 확정 → dataset validator → 모델 비교용 export.

센서 미연결·카메라 실패·모델 파일 없음에는 해당 기능과 시작 조건을 명확히 표시한다. Mock은 EMG·영상/landmark·동기 지연·실패·가림을 재현하고 모든 산출물에 synthetic=true를 남긴다. 실제와 모의 자료가 학습 export에 묵시적으로 섞이지 않게 한다.

## 11. 모델 중립 학습 입력 내보내기

학습 자체보다 재현 가능한 데이터 생성기를 구현한다.

- 분할은 raw window 생성 전에 participant_id로 수행한다. 동일 참가자의 방문·세트는 사람 독립 평가에서 같은 split이다. 기존 사람의 새 날짜 개인화 평가는 별도 실험으로 정의한다.
- train/validation/test split manifest와 seed를 저장한다. 입력/모델 선택은 validation, 최종 test는 선택 후 1회 평가 용도다.
- 고정 시간 window와 최근 K 반복 window를 후보로 지원한다. 길이·stride는 설정값이며 현재 완료 시점 이하 자료만 포함한다.
- tabular_features와 sequence arrays+mask를 각각 export한다. RAW/ENV와 시간·단위·채널 순서·가변 길이 mask를 명시한다.
- 반복 경계 검출에는 자세가 사용될 수 있으므로 `EMG-only`가 '예측 특징만 EMG'인지 '분절까지 EMG만'인지 명시한다. 후자를 주장하려면 독립 EMG 분절 경로가 필요하다.
- 입력 비교: EMG만 / 동작만 / EMG+동작, 그리고 인적정보·중량 추가 여부. 같은 예측 시점·가용 구간의 공통 평가 집합으로 비교하고 modality별 제외 비율도 보고한다.
- 후보 특징: RAW RMS·MAV, 유효 대역이 검증된 MDF/MNF, 최근 반복 변화량, ROM·템포·보상 정도. zero-phase 필터·세트 전체 정규화·미래 프레임 보간이 예측 입력에 미래 정보를 넣지 않도록 한다. 실시간용 causal 전처리 상태와 초기화 방법을 기록한다.
- 스케일러·결측 대치·특징 선택은 train에서만 fit한다. 참가자 baseline 보정은 해당 예측 시점 전에 얻은 calibration만 사용한다.
- forbidden feature: 최종 N, 종료시간, 종료 사유, 미래 EMG/자세, 최종 세트 통계, 검토용 정답 필드. ID도 모델 입력에 넣지 않는다.
- 향후 평가 지표를 export 문서에 명시: MAE, 실제 잔여가 적은 구간에서의 과대예측 빈도·크기, 참가자별 오차, 추론 시간. 실제 임계값은 분석 전에 고정한다.

## 12. 파일별 구현 가이드

| 기존/신규 경로 | 작업 |
|---|---|
| `config.py`, `models.py` | versioned schema, 채널 profile, set/rep/종료/동의 모델 |
| `acquisition/parser.py`, `serial_worker.py`, `time_unwrapper.py` | 프로토콜 판독, 수신시각·epoch·정합성 검증 |
| `acquisition/camera_worker.py` (신규) | 촬영시각·영상 segment·frame mapping |
| `pose/pose_worker.py`, `pose/metrics.py` (신규) | MediaPipe 추론·관절각·quality mask |
| `sync/clock_alignment.py` (신규) | epoch별 clock mapping·오차 진단 |
| `protocols/`, `labeling/` (신규) | 버전별 실험 기준, 반복 상태기계, annotation, RIR 라벨 |
| `storage/session_writer.py`, `dataset_store.py`, `exporter.py` | 다중 stream 저장·manifest·복구·allowlist export |
| `ui/participant_form.py`, `acquisition_panel.py`, `main_window.py`, `session_viewer.py` | 기존 위젯 확장, 미리보기·검토·세트 lifecycle |
| `scripts/validate_dataset.py` | v2/v3 분기, 참조·시각·라벨·완료 상태 검증 |
| `scripts/export_training_dataset.py` (신규) | split 우선, window/feature export·누수 검사 |
| `firmware/` | 기존 reference 보존, 이두·삼두용 신규 profile |
| `tests/`, `README.md`, `PROGRESS_REPORT.md`, `WorkOrder/` | 회귀/실패 테스트와 설치·실험·인계 문서 |

위 신규 경로는 제안이다. 기존 구조와 일관되게 조정하되 역할을 한 main_window 파일에 몰아넣지 않는다. PyQt6<6.8 제한은 Windows 검증 없이 제거하지 않는다. MediaPipe/OpenCV/NumPy 의존성을 실제 설치·import·카메라 실행으로 검증하고 검증된 환경을 남긴다.

## 13. TODO — 실제 작업 순서

- [ ] HEAD·AGENTS.md·기존 시험을 확인하고 baseline 결과 기록.
- [ ] 3절 fixture와 예상 실패를 먼저 구현·실행.
- [ ] v3 데이터 사전·채널 프로파일·기존 v2 읽기 확정.
- [ ] 참가자/방문/세트 메타데이터 및 동의·복장 확인 UI 확장.
- [ ] 카메라·MediaPipe·EMG 독립 수집과 timestamp 저장 구현.
- [ ] 동기화 진단·다중 stream writer·복구 구현.
- [ ] protocol 설정·반복 상태기계·종료 사유·판정불가 처리 구현.
- [ ] 영상 기반 검토·revision·라벨 생성 구현.
- [ ] split manifest·특징/window export와 validator 구현.
- [ ] 자동 테스트 → Mock 통합 → 실장치 파일럿 순서로 검증.
- [ ] 파일럿으로 동작 임계값·동기 오차·판정 일치도를 점검하고 protocol 동결.
- [ ] 본 수집 가능 여부와 남은 하드웨어 검증을 분리 보고.

## 14. 체크리스트 — 완료 판정과 테스트

- [ ] 기존 v2 상완요골근 데이터가 삼두로 바뀌지 않으며 뷰어/검증기가 읽는다.
- [ ] 새 헤더·프로파일 불일치, ADC 범위, 잘못된 시각, rollover/재부팅 테스트를 통과한다.
- [ ] 참가자 설문 0과 결측, 방문별 경과시간, 실제 중량·측정 팔이 보존된다.
- [ ] 15회 성공·16번째 실패 fixture에서 k=10/14/15의 라벨이 5/1/0이다.
- [ ] 자발적·통증·장비·추적 중단의 exact 라벨이 null이며 export에서 제외된다.
- [ ] 불완전 반복·가림·미러링·반복 경계 jitter로 중복 카운트나 거짓 실패를 만들지 않는다.
- [ ] 알려진 clock offset/drift와 드롭 fixture에서 오차·mask가 예상대로 기록된다.
- [ ] EMG/카메라 중단·디스크 부족·부분 finalize를 주입해 원본과 불완료 상태가 보존된다.
- [ ] 원시 영상 재생과 frame mapping, 수동 판정 revision 재현을 확인한다.
- [ ] participant split 교차 없음, window 미래 입력 없음, test fit 없음 검사가 통과한다.
- [ ] allowlist export에 이름·원본 영상·식별 메모가 없다.
- [ ] 기존 pytest 회귀 시험과 신규 핵심 시험의 실제 결과를 기록한다. 과거 passed 수를 재사용하지 않는다.
- [ ] 실제 ESP32+카메라로 지속 기록해 실측률·동기 품질·유실률을 보고한다. 장치가 없으면 해당 항목은 미검증이다.

자동 검증 예시 명령(구현 후 실행):

```bash
pytest -q
python scripts/validate_dataset.py <dataset-root>
python scripts/export_training_dataset.py --help
```

검증 스크립트는 위반 시 nonzero exit code와 set/stream/필드 단위 오류를 반환한다. 숫자로 정한 성능 기준은 실험 전에 설정 파일로 확정하고, 미달을 PASS로 바꾸지 않는다.

## 15. 최종 제출·인계

변경 코드, 신규 펌웨어 프로파일, 스키마/프로토콜 문서, synthetic 예제, 검증 스크립트, 실제 시험 로그, 사용자 수집·검토 설명서를 제출한다. 최종 보고는 변경 파일·이유·실행 명령·실제 결과·검증하지 못한 부분을 포함한다.

중단 시 `PROGRESS_REPORT.md`에 완료 항목, 현재 실패 재현 명령, 다음 TODO, 환경·프로토콜·스키마 버전, 로컬 데이터 위치(민감정보 제외)를 기록한다. 다음 작업자가 완료된 작업을 반복하지 않고 이어갈 수 있게 한다. 모델은 후보 상태를 유지하고 성능 결과 없이 하나를 확정하지 않는다.

## 16. 검토한 저장소 근거

아래 링크는 문서 작성 시 읽은 커밋으로 고정했다.

- [README와 현재 수집 구조](https://github.com/didtjr5080/EMGContloller/blob/58f8d4ab5135e2251b794cdeba54bb60cf4121db/README.md)
- [참가자·세션·샘플 모델](https://github.com/didtjr5080/EMGContloller/blob/58f8d4ab5135e2251b794cdeba54bb60cf4121db/src/emg_collector/models.py)
- [채널·프로토콜·스키마 설정](https://github.com/didtjr5080/EMGContloller/blob/58f8d4ab5135e2251b794cdeba54bb60cf4121db/src/emg_collector/config.py)
- [파서](https://github.com/didtjr5080/EMGContloller/blob/58f8d4ab5135e2251b794cdeba54bb60cf4121db/src/emg_collector/acquisition/parser.py)
- [현재 writer](https://github.com/didtjr5080/EMGContloller/blob/58f8d4ab5135e2251b794cdeba54bb60cf4121db/src/emg_collector/storage/session_writer.py)
- [참가자 폼](https://github.com/didtjr5080/EMGContloller/blob/58f8d4ab5135e2251b794cdeba54bb60cf4121db/src/emg_collector/ui/participant_form.py)
- [기존 펌웨어](https://github.com/didtjr5080/EMGContloller/blob/58f8d4ab5135e2251b794cdeba54bb60cf4121db/firmware/emg_streamer_reference.ino)
- [현재 의존성](https://github.com/didtjr5080/EMGContloller/blob/58f8d4ab5135e2251b794cdeba54bb60cf4121db/pyproject.toml)
