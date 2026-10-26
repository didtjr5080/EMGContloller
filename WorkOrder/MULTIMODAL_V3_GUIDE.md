# v3 멀티모달 수집·검토·export 안내

현재 단계는 **PILOT 소프트웨어**다. 실제 참가자 본 수집 승인이나 생리학적 한계 검증을 뜻하지 않는다.
한 기록은 한 팔·한 세트다. 여러 기록의 `visit_id`를 같게 두어 같은 방문에 연결한다.
세션 안의 `sets.csv`/`repetitions.csv`는 명시적인 `set_id`로 연결한다.
현재 UI는 세션당 한 세트를 지원한다. 양팔 동시 이두·삼두 측정은 지원하지 않는다.

## 설치·실행

Windows Python 3.12 권장. 프로젝트 루트에서:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev,multimodal]"
.venv\Scripts\python scripts/download_pose_model.py
.venv\Scripts\python -m emg_collector
```

실행하면 **이두·삼두 EMG + MediaPipe 동시 측정·자동 라벨링** 화면이 바로 열린다.
이두와 삼두는 같은 팔에 함께 부착하며 4개 ADC 값과 카메라/MediaPipe를 같은 세션에 수집한다.
기존 상완요골근 v2 화면이 필요하면 `python -m emg_collector --legacy-v2` 또는
`EMGController.exe --legacy-v2`로 명시적으로 연다. 과거 근육 이름을 삼두로 바꾸지 않는다.
v3에서 센서 1은 이두, 센서 2는 삼두다. legacy 헤더를 삼두로 재해석하는 우회 모드는 제공하지 않는다.

실제 실행 확인 환경: Windows, Python 3.12.8, PyQt6 6.7.0 / Qt 6.7.1,
pydantic 2.13.4, pyserial 3.5, MediaPipe 0.10.21,
opencv-contrib-python 4.10.0.84 (`cv2.__version__=4.10.0`), NumPy 1.26.4.
시험용 `.venv`는 호스트 site-packages를 참조한다. 호스트의 다른 OpenCV/NumPy/protobuf
패키지에 대한 pip 충돌 경고가 있었으므로 위 명령으로 새 격리 환경을 만들 수 있다.
MediaPipe import, 모델 로딩, 빈 이미지 추론과 모의 MJPG 인코딩/디코딩은 실제 실행했다.
실제 카메라 0번은 열리지 않았다. 다른 Python/Windows 조합은 검증하지 않았다.
PyQt6<6.8 제한은 유지했다.

## 모델·펌웨어

* API: MediaPipe Tasks `PoseLandmarker`, `RunningMode.VIDEO`, 한 사람.
* 모델: 공식 Pose Landmarker Lite float16, 버전 1.
* 로컬 경로: `models/pose_landmarker_lite.task` (Git 제외).
* SHA-256: `59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a`.
* 모델 누락·해시 불일치·추론 API 초기화 실패 시 실제 수집 시작을 차단한다.
* [공식 모델/API 안내](https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker/python),
  [고정한 Windows cp312 배포본](https://pypi.org/project/mediapipe/0.10.21/).

새 펌웨어는 `firmware/emg_streamer_biceps_triceps_v3.ino`다. 기존 reference는 보존했다.
핀은 이두 ENV 33/RAW 34, 삼두 ENV 32/RAW 35, 460800 baud, 500 Hz다.
시작 헤더는 `time_us,biceps_env,biceps_raw,triceps_env,triceps_raw`여야 한다.
앱이 헤더를 보지 못하면 보드를 리셋한다. 잘못된 프로파일 헤더는 즉시 차단한다.
보드 컴파일·업로드·실제 센서 배선·아날로그 대역은 이번 환경에서 확인하지 못했다.

## 수집 순서

창 모서리 드래그, 최소화·최대화, 우측 아래 크기 조절 손잡이를 사용할 수 있다.
좌우 설정/측정 경계와 영상/그래프 경계를 드래그해 비율을 바꾼다.
작은 창에서는 설정·조작 영역이 스크롤되며 기록 중지·통증 중지 버튼은 고정되어 보인다.
영상은 창에 맞춰 원래 비율로 축소/확대되고, 긴 동의 문구는 줄바꿈된다.
검토 화면도 영상/그래프·시도 표·검토 입력 영역 경계선을 드래그하고 입력 영역을 스크롤할 수 있다.

1. 신규 익명 ID 또는 기존 참가자를 선택한다. 이름은 선택 사항이며 private CSV에만 쓴다.
   설문은 최근 4주의 평소 주간 운동 기준이다. 미입력과 실제 0분을 구분한다.
2. 방문 ID, 최근 전체/상지 운동 후 경과시간, 방문별 피로·통증을 입력한다.
   값은 세션 스냅샷이므로 다음 방문 입력이 이전 방문을 바꾸지 않는다.
3. 측정 팔, 덤벨 한 개의 실제 중량, 세트 번호, 실제 휴식, 계획 반복 수를 입력한다.
   이두·삼두 부착 위치, 피부 준비·배선, 따뜻한 실내·전극 노출·가동범위를 확인한다.
   팔을 바꾸면 새 기록과 부착 기록을 작성한다. 옷/케이블 간섭은 `protocol_deviation`으로 종료하고
   검토 사유에 `clothing_interference`를 남긴다. 피로성 실패로 확정하지 않는다.
4. 연구·자세좌표·영상저장·영상접근·영상export 동의를 각각 확인한다.
   영상 미저장도 자세좌표 동의가 필요하다. 접근 가능한 객관적 영상 없이는 exact 라벨을 확정하지 않는다.
5. 카메라·시리얼·추적 점검을 누른다. 선택한 팔의 어깨·팔꿈치·손목·엉덩이가 보이는 측면 구도를 잡는다.
   사전 점검의 추적 품질은 시작 조건이며, 실제 동기 오차 검증을 대체하지 않는다.
6. [PILOT 프로토콜 JSON](unilateral_curl_pilot.json)을 선택하거나 기본 후보값을 사용한다. 코드에 있는 값은 실험 기준 후보다.
   승인된 표준으로 주장하지 않으며 현재 구현은 `PILOT`만 받는다.
7. 기록을 시작한다. worker는 EMG, 카메라/영상, MediaPipe 추론, 파일 저장으로 분리되어 있다.
   화면에는 RAW와 영상, 각도, 상태, 유효/무효/불명 시도 수가 나온다.
   이두·삼두·카메라를 별도로 녹화 시작할 필요가 없다. 시작 버튼 하나로 함께 수집한다.
8. 종료 사유와 실패 시도 유무/ID를 선택하고 중지한다. **통증 즉시 중지**는 사유 선택을 기다리지 않는다.
   창을 닫는 중지는 `other`로 보존하므로 이후 검토에서 사유를 수정한다.
   보조자 개입·중량 변경·긴 휴식은 protocol deviation 또는 새 세트로 분리한다.

종료 사유는 수집·검토 화면 모두 다음 한국어로 표시한다. 저장 코드는 기존 데이터와 호환된다.

| 화면 표시 | 저장 코드 |
|---|---|
| 기술적 실패 (자세 기준 미달) | technical_failure |
| 자발적 중단 | voluntary_stop |
| 통증·불편감 | pain_discomfort |
| 장비 이상 | equipment_failure |
| 자세 추적 실패 | tracking_failure |
| 측정 절차 이탈 | protocol_deviation |
| 계획된 종료 | planned_stop |
| 기타 | other |

## 시간·동기화·품질

시작 UTC와 host monotonic ns를 함께 저장한다. 시리얼 시각은 각 줄의 수신 직후이며,
장치 시각은 uint32 micros와 epoch 안의 unwrap 값이다. rollover는 같은 epoch,
반복 헤더 또는 경계 밖 1초 이상 역행은 새 epoch와 재부팅 추정 이벤트로 남긴다.
1초 이하 역행은 regression으로 세며, 작은 재부팅과 jitter를 확실하게 구분하지 못한다.
정확한 재부팅 식별이 필요하면 펌웨어 boot ID/하드웨어 트리거를 추가해야 한다.

카메라 시각은 **OpenCV read 완료 시각**이다. 노출 시각이 아니다. 인코딩 파일은 현재 세트당
MJPG AVI 한 segment이며 각 저장 프레임과 실제 host 시각을 별도 CSV로 연결한다.
추론 큐 크기는 2이고, 생략은 `inference_submitted=False` 및 별도 카운터에 기록한다.
카메라 내부의 원본 드롭은 관측할 수 없으므로 null이다. EMG 저장 큐 overflow는 세션 품질 실패다.

`sync.json`의 offset/drift/residual은 epoch별 소프트웨어 수신 회귀 추정이다.
일괄 수신 지연과 물리적 동기 오차를 없앴다는 뜻이 아니다. 시작·종료 software marker는
공통 host 시간축의 이벤트이며 공통 하드웨어 trigger가 아니다. 실제 sync error는 null로 남긴다.
파일럿에서는 시작·종료에 영상과 센서에서 함께 관측 가능한 별도 이벤트를 설계해
물리적 지연을 측정해야 한다. 현 구현에는 그 하드웨어 이벤트 입력/오차 검증 경로가 없다.
허용 오차 후보는 프로토콜에 있고 달성 상태는 false다.

normalized 좌표와 world 좌표는 분리하며, 2D 각도는 width/height를 반영한다.
추적 유실은 unknown이다. world 좌표는 MediaPipe의 추정이며 임상적 3D 측정이 아니다.
시각화는 원본 좌표를 미러링하지 않는다. 테스트에서 반사 시 각도 불변을 확인했다.

## 검토·revision·라벨

저장 세션 검토에서 공통 slider로 영상·EMG·각도를 탐색한다.
시도별 시간 경계, phase JSON, valid/invalid/unknown, 사유, ROM을 수정할 수 있다.
종료 사유와 최초 실패 attempt도 수정한다. 경계는 host monotonic ns 단위다.
자동 판정과 원본 CSV는 그대로 두고 `annotations.jsonl`에 reviewer ID·시각·사유·이전 revision을 쓴다.
타임아웃/불완전 시도도 보존하며, 자동 결과가 세트 종료를 확정하지 않는다.

첫 검토는 provisional이다. PILOT에서는 서로 다른 두 검토자가 먼저 독립 평가하고,
판정 일치 또는 명시적인 불일치 조정을 기록해야 confirmed가 된다.
현재 UI는 이전 revision을 숨기는 맹검 도구는 아니므로 독립 평가는 운영 절차로 관리한다.
revision에 유효성 일치율·kappa·경계 MAE(ms)를 기록한다. 외부 각도 정답이 없어 각도 오차는 null이다.

정확한 N-k는 **접근 동의 영상 + 두 검토 + 기술적 실패 + definite failed attempt**일 때만 만든다.
가림으로 실패 전 시도가 unknown이면 exact 확정을 거절한다. 실패 후 반동 반복은 N에 더하지 않는다.
자발적·통증·장비·추적·계획 중단의 remaining은 null이며 초기 exact export에서 제외한다.
`observed_valid_count`, `censoring_status`로 관찰값과 검열 상태를 별도로 보존한다.
`next_attempt_failure`는 바로 다음 검토 시도가 terminal failure인지를 뜻하며 `remaining<=1`과 다르다.

## 두 근육과 MediaPipe 라벨을 한 CSV로 확인

기록 종료 시 같은 세션에 `labeled_samples.csv`가 자동 생성된다. 한 행이 EMG 한 샘플이다.
이두 ENV/RAW·삼두 ENV/RAW와 다음 값이 함께 들어간다.

* host/device 시각·epoch, 연결한 pose frame ID와 촬영/추론 시각, 자세와의 시간 차이.
* 팔꿈치 각도·몸통 기울기·상완 변화, 자세 유효 mask.
* `phase`: ready/concentric/top/eccentric/completed/unknown.
* `attempt_id`, `attempt_validity`: valid/invalid/unknown, 라벨 출처·검토 상태·revision·synthetic.

500Hz EMG와 약 30fps 자세를 같은 행 번호로 붙이지 않는다. 샘플 시각 이하의 가장 가까운
pose를 최대 허용 gap 안에서 연결한다. 가림/공백은 phase=unknown으로 보존한다.
두 근육에 붙는 것은 같은 동작/반복 라벨이며, MediaPipe만으로 각 근육의 전기적 활성 여부를 단정하지 않는다.
자동 라벨 CSV는 원본으로 보존하며 모든 자동 결과는 provisional이다.
검토 수정 후에는 검토 창의 **저장된 검토 라벨 + 이두·삼두 EMG CSV 내보내기**로
해당 revision의 새 CSV를 만든다. 원본 EMG·자세·자동 라벨은 덮어쓰지 않는다.

이 통합 CSV의 반복 유효성은 반복 종료 후 확정한 사후 라벨이다. 온라인 예측 특징으로
그 유효성/미래 결과 열을 넣지 않는다. 인과적 모델 입력은 기존 training exporter를 사용한다.
시간 연결은 software-only이며 물리적 sync 오차는 파일럿에서 측정해야 한다.

## 저장·복구

루트 registry/manifest는 v2 호환 형식이고, 개별 `metadata.json.schema_version`이 reader를 결정한다.
v2는 상완요골근 그대로 읽는다. v1은 미지원 오류를 낸다. 과거 자료를 제자리 변환하지 않는다.
모든 스트림은 `.part`로 쓰고 close/flush/fsync 후 순서대로 rename한다.
여러 파일의 rename 전체를 원자적이라고 보장하지 않는다. manifest는 마지막에 교체한다.
영상 decode와 frame mapping, 파일별 SHA-256·행수를 검사한다.

앱 재시작 시 v3 미완료 manifest를 감지한다. 복구는 텍스트의 `.part.recovered` 복사본을 만들고
원본/기존 완성 파일을 보존한다. 복구 상태는 **incomplete**이며 영상만 손상되어도 complete로 승격하지 않는다.
완전한 자동 영상 수리나 복구 세트의 자동 라벨 확정은 제공하지 않는다.

## 재현 가능한 synthetic 예제와 export

아래 출력 폴더는 새 경로여야 한다. 기존 폴더를 덮어쓰지 않는다.

```powershell
.venv\Scripts\python scripts/create_synthetic_dataset.py datasets/synthetic_new
.venv\Scripts\python scripts/validate_dataset.py datasets/synthetic_new
.venv\Scripts\python scripts/export_training_dataset.py datasets/synthetic_new datasets/training_new --synthetic --allow-pilot
# 최근 3회 반복 window, 2회마다 예측 시점 선택
.venv\Scripts\python scripts/export_training_dataset.py datasets/synthetic_new datasets/training_k3 --synthetic --allow-pilot --last-k 3 --stride-reps 2
```

예제는 실시간 녹화 검증용이 아닌 결정적 fixture다. 500 Hz 24,001 samples, 10 fps 481 frames,
15회 유효+16번째 실패, 재생 가능한 MJPG 영상과 두 synthetic reviewer revision이 있다.
실시간 Mock UI는 약 30fps 카메라와 EMG를 별도로 생성하며 가림과 50 sample마다의 수신 batch 지연도 주입할 수 있다.
두 모의 경로의 모든 자료는 부모 metadata/manifest의 synthetic=true를 상속한다.

split은 window 전에 participant_id별 SHA-256(seed:ID), 70/15/15 비율로 정한다.
같은 참가자의 모든 방문/세트/겹치는 window는 같은 split이다. 작은 코호트는 빈 split이 가능하다.
고정 시간 또는 최근 K 반복 window, 반복 단위 stride를 지원한다. 예측 시점은 유효 반복 완료 직후다.
촬영 경계(prediction_capture_ns)와 추론·debounce 완료 시점(decision_host_ns)을 구분한다.
window에는 촬영 경계 이하 측정값 중 결정 시점까지 수신된 EMG와 추론 완료된 pose만 들어간다.
pose는 causal previous-neighbor로 연결하고 최대 gap 초과 시 0+mask=False를 쓴다.

`tabular_features.csv`와 `sequences/*.npz`(values/mask/host_ns), 별도 target/index,
split/export manifest를 만든다. 시퀀스 채널 순서·단위·전처리는 manifest에 있다.
EMG-only는 예측 특징만 EMG라는 뜻이며 분절까지 EMG-only라는 주장은 하지 않는다.
EMG/동작/결합은 같은 index로 비교한다. 제외 사유별 수를 기록한다.
`--include-personal`, `--include-load`는 명시적 옵션이다.
MDF/MNF는 아날로그 대역 미검증으로 제외한다. fit/필터/정규화는 수행하지 않는다.
RMS/MAV에 고정 ADC 중간값 2048을 빼며 세트 전체 통계나 미래 자료를 사용하지 않는다.
후속 scaler/imputer/특징 선택은 train만 fit해야 한다. 최종 test는 선택 후 1회 평가한다.

ID는 index 참조용이며 모델 입력이 아니다. 종료 사유·N·최종 세트 통계·검토용 정답은
feature 테이블에 없다. ROM 특징은 이용 가능한 pose에서 다시 계산한다.
이름·자유메모·영상·영상경로는 allowlist에서 제외된다. 신호 보관용
`export_deidentified()`도 allowlist를 사용하며 학습 export와 별도의 archive다.
실제/모의 모드를 묵시적으로 혼합하지 않는다. 모든 출력은 연구자료이며 Git에 넣지 않는다.
후보 모델은 Ridge/SVR/RF/XGBoost/CNN/RNN/TCN 등으로 유지하며 이번 작업에서 선정하지 않는다.

상세 필드 규칙은 [데이터 사전](MULTIMODAL_V3_SCHEMA.md)을 참조한다.

## 코드 리뷰 수정 후 수집·검토·export

수신이 시작되지 않거나 정상 EMG 수신이 멈추면 watchdog이 장치 장애로 중단한다.
잘못된 행·boot 로그는 유효 샘플을 대신하지 않는다. camera/pose 정체도 검사한다.
오류 세션은 미완료로 표시하며, 원본과 마지막 유효 데이터는 보존하고 exact로 확정하지 않는다.

검토 창의 독립 판정은 원 자동 시도 목록부터 시작하고 이전 사람 판정을 숨긴다.
영상과 EMG·각도를 확인하여 객관적 검토 체크, 검토자 ID와 근거를 기록한다.
ID 입력은 인증 기능이 아니므로 실제 독립 검토자 운영은 연구자가 관리한다.
서로 다른 두 완료 평가가 일치하면 확정하고, 불일치하면 조정 모드에서 두 assessment를
선택하여 차이를 확인하고 해결 근거를 저장한다. 초안은 독립 완료 평가에 포함되지 않는다.
삭제·분할한 terminal failure는 다시 선택해야 한다. 시도 ID는 직접 변경할 수 없다.
추가·분할·병합된 시도는 unknown으로 시작하므로 경계·유효성·phase를 검토한다.
누군가 먼저 저장했다면 재불러오기 후 다시 검토한다. 저장 중 실패한 거래는
검토 창의 복구 버튼으로 복구할 수 있고, 복구 전에는 미확정 상태다.

실장치 EMG는 host_receive_ns만으로 물리 동기를 입증할 수 없다.
reference event로 검증된 mapping이 없는 기본 라벨은 alignment_unverified이며
기본 학습 export에서 제외한다. known synthetic mapping은 모의 데이터에만 적용된다.
mapping 교체는 publish_alignment()로 별도 파생 파일을 발행하며 acquisition을 덮어쓰지 않는다.
정렬·원시 근거가 바뀌면 예전 확정은 해제되어 재평가가 필요하다.

```powershell
# integrity와 signal quality를 별도 JSON 결과로 확인
.venv\Scripts\python scripts/validate_dataset.py datasets/synthetic_new --quality-report build/quality.json
# 기본값: 미완료/손상/미검토 세션 격리 후 정상 세션 계속 출력
.venv\Scripts\python scripts/export_training_dataset.py datasets/synthetic_new datasets/export_new --synthetic --allow-pilot
# 관련 세션/창 제외가 발생하면 전체 중단 (완료 manifest 없음)
.venv\Scripts\python scripts/export_training_dataset.py datasets/synthetic_new datasets/export_strict --synthetic --allow-pilot --strict
# 물리 동기 미검증 추정 mapping의 파일럿 진단에만 명시적으로 허용
.venv\Scripts\python scripts/export_training_dataset.py datasets/real_pilot datasets/diagnostic_new --allow-pilot --allow-unverified-alignment
```

UI의 장치·진단 설정 창에 있는 진단용 export 체크도 동일한 옵션이다. 미검증 허용은 gap·clipping 등 품질 검사를 우회하지 않는다.
경고·policy·정렬/검토 버전과 창별 품질, exclusion_report.json을 함께 확인한다.
미검증 mapping조차 없거나 사용 가능 시점 조건을 충족하지 못하면 진단 export도 0예제일 수 있다.
0예제나 빈 train/validation/test split은 학습 준비 완료가 아니다. 출력 경로는 새 경로를 사용한다.
이번 재현 예제는 datasets/review_fixes_20261026, strict 결과는 datasets/review_fixes_training_20261026이다.

## 필수 입력만 표시하는 수집 화면

기본 v3 화면에서 식별용 이름(선택), 나이, 키, 주당 운동 횟수, 최근 운동 후 경과일을 입력한다.
기존/신규 참가자 구분과 ID 생성 조작, 방문 유지, 세트 번호 입력은 제공하지 않는다.
시리얼 포트·카메라, 측정 팔·실제 중량·전극 위치를 확인하고 동의와 장치 점검 후 기록을 시작한다.
체크박스는 연구 참여·자세 좌표·원본 영상 저장·검토자 영상 접근 동의 4개뿐이다.
Mock/가림/진단 선택은 별도 설정 창의 선택 목록으로 유지한다.
한 번 측정이 시작되면 같은 화면에서 다시 측정할 수 없다. 다음 측정은 앱을 새로 실행한다.
자동 ID는 파일 참조에만 사용하며 측정 간 연결이나 기존 기록 불러오기에 사용하지 않는다.
이름은 participants_private.csv에 ID와 함께 저장하고 공개 CSV·metadata·학습 feature에 넣지 않는다.
피부·복장 확인을 수집하지 않으므로 skin_prepared/clothing_confirmed는 False,
metadata.preparation_confirmation은 not_confirmed로 기록한다. 자동으로 확인 완료라고 저장하지 않는다.
덤벨 무게는 한 개당 kg이며, 덤벨 개수는 별도 입력칸에서 수정한다(기본 1개, 1~100개).
기존 고정 설명인 'kg / 덤벨 1개'를 없애고 두 값을 각각 저장한다.
검토 기록에도 개수를 보존하며 --include-load export에는 무게와 개수가 함께 포함된다.
영상 저장·접근 동의는 사용자가 직접 선택하며, 객관적 영상 검토를 하려면 두 동의가 필요하다.
기존처럼 중지·통증 중지 버튼은 고정되고, 종료 사유와 실패 시도 선택을 유지한다.

성별·몸무게·주당 운동 시간·근력운동 횟수/경력·주사용 팔·메모와
방문 피로/통증/운동 후 시간·계획 반복 수·휴식은 새 v3 수집에서 입력받지 않는다.
선택 데이터는 null/unspecified/빈 메모 등 기존 스키마 기본값을 사용한다.
숨겨진 선택 위젯에 값이 남아 있어도 새 참가자 스냅샷으로 수집하지 않는다.
방문 ID는 내부 고유값으로 자동 생성하고 세트 번호는 내부값 1, 영상 내보내기 동의는 False다. 기존 저장 파일은 수정하지 않는다.

일반 장치 설정은 포트와 카메라만 표시한다. 모델 경로·프로토콜 선택·Mock과 가림/지연 주입·
미검증 정렬 진단 옵션은 별도 **장치·진단 설정** 창에서 연다.
세션 검토·학습 export·미완료 복구는 **저장 데이터 관리** 메뉴에서 실행한다.
기존 v2 화면의 입력과 데이터 모델은 유지한다.
