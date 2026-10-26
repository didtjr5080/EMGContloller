# EMG Dataset Collector — 진행 현황 공유

## 2026-10-26 — 이름 입력과 단회 측정 흐름

사용자 요청으로 기본 v3의 기존/신규 선택·ID 생성 UI·세트 번호·피부/복장 체크를 제거했다.
이름(선택)은 ParticipantPrivate와 participants_private.csv로만 저장하며 공개 참가자/metadata에 넣지 않는다.
체크박스는 연구·자세 좌표·영상 저장·영상 접근 동의 4개다. 장치/Mock/진단은 선택 목록이다.
내부 참가자/방문 ID는 자동 생성하며 이전 사용자 불러오기나 날짜별 방문 연결을 제공하지 않는다.
측정 시작 후 같은 창에서 두 번째 측정을 차단하고, 완료 후 입력/시작은 다시 활성화하지 않는다.
다음 측정은 앱을 새로 실행한다. 이름만으로 실제 사람의 신원을 인증하거나 재실행까지 중복을 차단하지는 않는다.
피부/복장 확인을 받지 않은 값을 자동 True로 만들지 않도록 controller의 준비 확인 필수 gate를
전극 위치 필수 검사로 변경하고 preparation_confirmation=not_confirmed와 False 값을 보존한다.
연구/자세 동의와 장치 점검은 계속 필요하다. 기존 v2와 원본 자료는 유지한다.
검증: **121 passed in 41.30s**, Ruff F/Black 통과. 동의 체크만 존재, 이름 private 저장,
공개 파일에서 이름 제외, 완료 후 재시작 및 중복 등록 차단, 준비 미확인 값 저장을 검사했다.
실제 로그 build/single_measurement_tests.txt. Windows 재빌드 결과는 WorkOrder/WINDOWS_EXE_BUILD.md.
EXE 재빌드·자체 시험·Python 경로 제거 독립 실행 모두 성공했다.
독립 실행 EMG/라벨508행·영상19프레임·validator 오류0. EXE185,544,261 bytes,
SHA256 715a1a224077dd73ceacbd27496ca6b58887de9958aba6dd5c3565309b957ef0.
맑은 고딕을 직접 로드한 1100×780/640×480 화면은 build/single_measurement*.png로 확인했다.
실제 장치 연결은 미검증이다.

## 2026-10-26 — 덤벨 무게·개수 분리 입력

중량 칸의 '덤벨 1개'는 고정 suffix여서 사용자가 개수를 바꿀 수 없었다.
무게는 kg 입력(화살표 0.5kg 간격), 개수는 별도 정수 입력(1~100개)으로 분리했다.
두 값은 controller → metadata.equipment 및 sets.csv → review snapshot으로 보존한다.
--include-load 학습 feature에도 load_kg와 dumbbell_count를 함께 제공한다.
기존 개수 없는 CSV/review는 1개로 읽고, 독립 판정 비교에서도 생략/기본1은 같은 값으로 취급한다.
기존 데이터 파일은 제자리 수정하지 않는다. load_kg는 계속 한 개당 무게이며 합산으로 바꾸지 않는다.
전체 시험 **121 passed in 53.29s**, 변경 파일 Ruff F·Black 확인 통과.
화살표로 5→5.5kg/1→2개 입력, controller 전달, 실제 모의 세션 저장값,
기존 판정의 생략/기본값 동등 비교, --include-load feature 두 열을 검사했다.
실제 시험 로그: build/dumbbell_tests_final.txt. 실행 파일 해시/자체 시험은 WorkOrder/WINDOWS_EXE_BUILD.md.
첫 재빌드 자체 시험은 writer_shutdown_timeout으로 실패했고 로그는
build/dumbbell_first_exe_failure.json에 보존했다. EXE 점검용 synthetic 세션에만
종료 대기 20초·전체 완료 대기 45초를 적용했다. 일반 수집의 기본 watchdog 정책은 유지한다.
EXE 점검은 실장치 지연이나 성능을 검증하는 시험이 아니며, 단발 지연의 원인은 미확정이다.
최종 EXE 자체 시험 및 Python 경로 제거 독립 실행 모두 exit0/ok=true.
독립 실행 EMG/라벨492행·영상21프레임·validator 오류0. EXE185,545,879 bytes,
SHA256 5dcc1cebf212afda04367bcfef5334a5c30b6e00a8018cb5f2d9c0b02221190f.

## 2026-10-26 — 수집 화면 필수 정보만 표시

기본 v3에서 선택 참가자 정보·방문 상태 설문·계획 반복·휴식 입력을 제외했다.
필수 참가자/측정/전극 정보·준비·명시적 동의를 남기고, 모델/프로토콜/Mock/진단은
별도 장치·진단 설정 창으로, 검토/export/복구는 저장 데이터 관리 메뉴로 옮겼다.
방문 ID는 날짜로 자동 생성하며 영상 내보내기 동의는 False를 유지한다.
ParticipantForm(required_only=True)는 숨겨진 선택값도 새 모델에 포함하지 않는다.
v2 입력·기존 기록은 유지했다. 오류가 없을 때 빈 오류 행도 숨겨 불필요한 간격을 줄였다.
검증: **120 passed in 69.01s**, 수정 UI Ruff F 통과. 맑은 고딕을 직접 로드하여
1100×780/640×480 화면 배치와 고정 중지 버튼을 확인했다(build/minimal_collection*.png).
실행 파일도 새 화면으로 재빌드하며 결과/해시는 WorkOrder/WINDOWS_EXE_BUILD.md에 기록한다.
재빌드 완료: 185,545,242 bytes, SHA256 0178dcddfa12be71200d75dd3aabae9ad382a607f28198940dd06761907e4ec5.
EXE 자체 시험 통과. Python 경로 제거 독립 실행은 첫 시도 영상 worker 종료 timeout으로
실패하여 로그를 보존했고, 동일 조건 재실행은 exit0/ok=true(EMG/라벨493행·영상21프레임).
단발 지연 원인은 미확정이며 실장치 연결은 확인하지 않았다.

## 2026-10-26 — 코드 리뷰 F1~F6 후속 수정

시작 HEAD: 829e24c932dbaaaf61bacc8b7dd449decdff6df4 (리뷰 기준과 동일).
baseline 81 passed/13.63s, 새 최소 재현 6 failed/9.35s를 실제 실행했다.
F1 측정/가용 시각·epoch mapping, F2 창 품질, F3 수집 watchdog·bounded 종료,
F4 세션 격리·transactional export, F5 부분 반복·시도 편집,
F6 독립 완료 평가·조정·CAS·복구를 구현했다.
전체 회귀: **118 passed in 68.48s**. 합성 새 예제의 validator 무결성 오류0,
품질500Hz/coverage1.0/gap2ms, strict export15예제(빈 validation/test 명시).
계약: schema3.0.0, alignment-1, emg-quality-1(PILOT), watchdog-1, review-2, review-fixes-1.
원본 자료·영상·v2 reader는 유지했다. 과거 근거 없는 확정은 provisional로 취급한다.
상세 재현·수정 위치·실행 명령·호환성: WorkOrder/CODE_REVIEW_FIX_REPORT.md.
Windows 재빌드/자체 점검 결과는 WorkOrder/WINDOWS_EXE_BUILD.md에 기록한다.
재빌드·Python 경로 제거 독립 실행 모두 exit0/ok=true. EXE 185,545,037 bytes,
SHA256 637808f2c7a0cb37f1c33723fad7d7e39c3f398783d7e46acf37b701f9a0bbac.
독립 점검에서 EMG/통합 라벨500행·영상22프레임, validator 오류0,
작은 창/한국어 종료 선택지 확인. 소프트웨어 TODO는 완료했다.
실제 장치 물리 동기와 파일럿 측정은 장치 미사용으로 미검증이다.

## 2026-10-26 — 화면 크기 조절·종료 사유 한국어 표시

수집·검토 창에 최소화/최대화 버튼과 크기 조절 손잡이를 추가하고 시작 크기를 모니터 가용 영역에 맞춘다.
고정 영상 크기를 제거해 원본 비율로 자동 축소/확대한다. 패널 경계선은 드래그로 조절하며,
설정·조작·검토 입력은 스크롤된다. 수집 중지·통증 중지 버튼은 화면 아래에 고정한다.
긴 동의/설문/설명 문구도 줄바꿈되므로 작은 창에서 입력란이 밀려나지 않는다.

종료 사유 8개는 수집·검토 화면 모두 한국어로 표시한다. 저장 enum 코드는 보존해 기존 데이터·판정과 호환된다.
변경 중심: `ui/common.py`, `multimodal_panel.py`, `multimodal_review.py`, `participant_form.py`.
시험: **81 passed in 14.94s**. 640×480/800×600 크기, 영상 프레임 크기 변화,
중지 버튼 가시성·스크롤, 동의 문구 클릭, 한국어 표시/저장값을 확인했다.
맑은 고딕을 적용한 640×480 수집·검토 화면도 별도 확인했다.
exe 자체 점검에 작은 창과 한국어 선택지 검사를 추가했다. 산출물 검증 결과는 `WorkOrder/WINDOWS_EXE_BUILD.md`.
재빌드 exe의 독립 실행 점검 exit 0, 작은 창/한국어 검사 true, 모의 EMG·라벨 493행과 영상 23프레임,
validator 오류 없음. Python 경로를 제외하고 다른 작업 폴더에서 실행한 결과다.

## 2026-10-26 — 이두·삼두 + MediaPipe 동시 수집·라벨 연결 기본값

사용자 확인에 따라 실행 기본 화면을 이두·삼두 + MediaPipe 수집 창으로 변경했다.
이두·상완요골근 기존 화면은 `--legacy-v2`로 명시적으로 연다.
한 번의 시작/중지로 같은 팔의 두 근육 4 ADC와 카메라/MediaPipe를 함께 기록한다.

기록 종료 시 `labeled_samples.csv`를 자동 생성한다. 각 EMG 행의 이두·삼두 ENV/RAW,
host/device 시각과 MediaPipe frame/각도/동작 단계/반복 ID/validity를 함께 저장한다.
행 번호가 아닌 시각으로 연결하고, 가림·긴 gap은 unknown으로 보존한다.
자동 파일은 provisional 원본으로 보존한다. 검토 화면에서 저장된 revision의
라벨+EMG를 새 CSV로 내보낼 수 있으며, 원본/자동 판정은 덮어쓰지 않는다.
자동 라벨은 사후 동작/반복 라벨이며 근육 전기활성이나 실시간 예측 입력의 정답 특징이 아니다.

시험: **76 passed in 11.69s**. 신규 확인: 기본 화면, 두 근육 값 보존·동일 시각 라벨,
미래/오래된 pose·가림 unknown, legacy 재해석 차단, 검토 revision CSV와 자동 원본 불변.
예제 `datasets/simultaneous_20261026`: EMG+라벨 **24,001행**, validator 통과.
샘플 100은 이두 RAW 2000 / 삼두 RAW 2100 / pose frame 2 / concentric / attempt A1 / valid.

`dist/EMGController.exe`를 재빌드했다. 단독 실행 점검 exit 0, 기본 모드 확인,
EMG 502행·영상 26프레임·MediaPipe 연결 라벨 502행, validator 오류 없음.
Python 경로를 제외하고 다른 작업 폴더에서 실행한 결과다.
상세 산출물 정보: `WorkOrder/WINDOWS_EXE_BUILD.md`.
실장치 시간 오차/동작 기준은 여전히 미검증이며 PILOT 제한을 유지한다.

## 2026-10-26 — Windows 단일 실행 파일 추가

`dist/EMGController.exe`를 생성했다. Python과 MediaPipe 모델 포함, 약 177 MiB.
더블클릭 실행하며 수집 자료는 exe 옆 `datasets`에 저장한다.
소스 시험 **69개 통과**, exe 자체의 모델 추론·Qt 화면·모의 EMG/MJPG 수집·검토·validator 통과.
다른 작업 폴더 및 Python 경로를 제외한 PATH에서도 self-test exit 0을 확인했다.
재현 빌드는 `scripts/build_windows.ps1`, 세부 결과는 `WorkOrder/WINDOWS_EXE_BUILD.md`.
실장치 검증과 PILOT 제한은 아래 보고와 같다.

## 2026-10-26 — 멀티모달 지시서 실행 결과

대상: `WorkOrder/EMGController_Multimodal_Collection_Work_Order.md`.
시작 HEAD `58f8d4ab5135e2251b794cdeba54bb60cf4121db`는 지시서와 같았다.
사용자가 제공한 미추적 지시서는 보존했다. 기존 아래 보고는 10월 6일의 과거 기록이다.

### 이번 구현

- v3.0.0 명시적 이두·삼두 프로파일, 기존 v2 상완요골근 reader/뷰어/validator 유지.
  신규 펌웨어 별도 추가, legacy reference 보존. 양쪽 parser 모두 다른 근육 헤더의 묵시적 재해석 차단.
- 익명 참가자·선택적 private 이름, 설문 0/미입력 분리, 운동 경력·방문 상태 스냅샷,
  분리된 동의, 부착·복장·실제 팔/중량/휴식/계획 반복 확인 UI.
- 기존 PyQt 창에서 v3 수집과 검토 진입. 카메라·EMG·MediaPipe·writer 독립 worker,
  유계 큐, host timestamp/epoch, software clock fit, 원본 프레임 mapping과 MJPG 영상.
- PILOT 프로토콜, debounce/hysteresis 반복 상태기계, partial/timeout/unknown 보존,
  종료 사유·실패 시도 ID/유무, 즉시 통증 중단.
- 영상·EMG·각도 공통 탐색, 수동 경계/판정 수정, append-only revision,
  서로 다른 두 검토자 일치/조정 후 라벨 확정, 일치율/kappa/경계 오차 기록.
- 파일별 hash/행수/영상 decode/프레임 매핑과 마지막 completion manifest.
  큐 초과·디스크/부분 finalize는 incomplete. 복구는 원본 보존 복사본이며 자동 완료/정답 승격 금지.
- participant 우선 split, 고정 시간/최근 K 반복 causal window, tabular/sequence+mask,
  EMG/동작/결합 공통 index, 선택적 인적정보·중량, 검열 자료 제외, 미래 추론 제외,
  allowlist export. 모델 학습/최종 모델 선정은 하지 않음.
- synthetic 예제 생성기, schema 사전·수집/검토 안내·검증 스크립트와 실패/통합 시험.

### 실제 실행 결과

환경: Windows Python 3.12.8, PyQt6 6.7.0 / Qt 6.7.1, pydantic 2.13.4,
pyserial 3.5, MediaPipe 0.10.21, opencv-contrib-python 4.10.0.84, NumPy 1.26.4.
기본 환경의 경로/pyserial 미설치 오류를 분리한 후 기존 시험 33개 통과.
최종 `.venv\Scripts\python -m pytest -q`: **67 passed in 9.38s**.
출력: `WorkOrder/MULTIMODAL_TEST_RESULTS.txt`.

| 명령/검사 | 실제 결과 |
|---|---|
| `scripts/create_synthetic_dataset.py datasets/synthetic_20261026` | 생성 완료: EMG 24,001행, 영상/pose 481프레임, 16시도, 2개 synthetic 검토 revision |
| `scripts/validate_dataset.py datasets/synthetic_20261026` | `OK: dataset passed all integrity checks` |
| `scripts/export_training_dataset.py datasets/synthetic_20261026 datasets/training_20261026 --synthetic --allow-pilot` | 15개 예제, 제외 없음; k=10/14/15 → 5/1/0 |
| 같은 export에 `--last-k 3 --stride-reps 2` | 별도 출력 `datasets/training_k3_20261026`, 8개 예제 |
| 공식 Pose Lite 모델 로딩 + 640×480 검은 영상 Tasks 추론 | 성공; landmark 0개 (빈 영상 예상 결과) |
| 실제 카메라 index 0 open/read | 둘 다 False, 실제 카메라 수집 미검증 |
| 직렬 포트 열거 | 포트 존재만 확인; ESP32 식별·연결·기록은 실행하지 않음 |

로컬 synthetic 산출물과 모델은 `datasets/`, `models/` 아래이며 Git 제외.
원본/학습 export의 경로 이름에 v2가 붙은 초기 디버깅 산출물도 모두 schema v3 synthetic이다.
최종 확인용 경로는 위 `*_20261026`이다. 실제 참가자/개인 영상은 생성하지 않았다.

### 완료 범위와 다음 TODO

소프트웨어 자동 검증·모의 통합까지 완료. **본 수집 준비 완료로 판정하지 않는다.**

1. 실제 ESP32 새 펌웨어의 컴파일/업로드, 센서 부착·배선·ADC/아날로그 anti-alias 대역 확인.
2. 사용 가능한 실제 카메라로 측면 구도·노출/가림·영상 codec 재생과 장시간 동시 기록 검증.
3. 공통 관측 이벤트/하드웨어 trigger를 설계하고 지연·동기 오차·유실률·실측 Hz/fps 측정.
   현재 software marker/수신 회귀의 물리적 오차는 null이며 동기 목표 달성을 주장하지 않음.
4. 교수 검토와 두 사람의 독립 파일럿으로 각도·템포·보상·종료 기준 및 판정 신뢰도 확정.
   현재 프로토콜 0.1.0은 PILOT 전용이고 승인/freeze 전환은 제공하지 않는다.
5. 실제 연구의 승인된 protocol·동기 품질 조건을 정한 뒤 본 수집 허용 gate를 확장.

제한: 현 UI는 한 세션에 한 세트, 영상은 세트당 MJPG 한 segment, v1 미지원,
복구된/손상된 영상의 자동 수리는 없음. 맹검 평가는 UI가 강제하지 않아 운영 절차가 필요.
미세 재부팅과 timer jitter의 완전한 구분에는 펌웨어 boot ID가 필요하다.
MDF/MNF·각도 ground truth 오차·물리적 sync 오차는 미검증으로 유지한다.

인계 문서: `WorkOrder/MULTIMODAL_V3_GUIDE.md`, `WorkOrder/MULTIMODAL_V3_SCHEMA.md`,
`WorkOrder/MULTIMODAL_EXECUTION_LOG.md`. 재현 실패 명령이 있다면 validator가 세션/stream/필드를 표시하며
nonzero로 종료한다. 현재 자동 시험 실패 없음. 기존 과거 보고의 시험 수와 구별한다.

> 기준 문서: `WorkOrder/Codex_EMG_Dataset_Collector_Work_Order.md`
> 최종 갱신: 2026-10-06

## 1. 요약

ESP32 기반 EMG 데이터셋 수집 데스크톱 앱(Python + PyQt6)을 처음부터 구현했다. 처음에는 MyoWare 2.0 센서 1개(3컬럼) 기준이었으나, 실제 하드웨어가 센서 2개(이두근 + 상완요골근, 4개 ADC 핀)로 바뀌면서 앱 전체를 **2채널(schema v2)**로 마이그레이션했다. 모의(Mock) 신호로 전체 기능이 검증되었고, 자동화 테스트 33개가 모두 통과한다. **실제 ESP32 하드웨어로 2채널 녹화가 끝까지 정상 동작하는지는 아직 현장에서 재확인이 필요하다** (파서 레벨에서는 실제 캡처 데이터로 검증 완료).

## 2. 구현된 기능

- ESP32 `time_us,biceps_env,biceps_raw,brachio_env,brachio_raw` CSV 스트림(460800 baud, 500 Hz) 파싱 + 진단 카운터(잘못된 행/범위 오류/헤더/부팅 메시지 구분)
- 32-bit `micros()` 순환과 장치 재부팅을 구분하는 시간 보정 로직
- 시리얼 읽기·CSV 저장을 GUI 스레드에서 분리(QThread 기반 `SerialWorker`), 배치 단위 전달
- `.part` 파일 → 원자적 rename 방식의 저장, 비정상 종료 시 자동 감지 및 복구 제안
- 피험자 식별정보(`participants_private.csv`)와 비식별 메타데이터(`participants_public.csv`) 분리 저장
- 측정 세션 메타데이터, 라벨/이벤트 기록, 연구 동의 확인 없이는 기록 시작 불가
- **RAW/ENV 실시간 그래프 — 이두근·상완요골근 2채널 동시 표시** (각 그래프에 곡선 2개 + 범례), 표시 정지와 데이터 저장 분리, 세션당 품질 지표(`quality.json`, 채널별 min/max/mean/std) 자동 계산
- 하드웨어 없이 2채널 전체 기능을 검증할 수 있는 모의 신호 모드(오류 주입 포함)
- 비식별 데이터셋 내보내기, 데이터셋 무결성 검증 스크립트
- 저장된 세션 불러오기: 과거에 기록한 세션(정상 종료분은 물론, 비정상 종료된 `.part` 세션까지)을 별도 창에서 4채널 전체 파형 + 이벤트 마커 + 메타데이터/품질 요약으로 다시 볼 수 있음
- **[신규] `scripts/emg_2ch_logger.py`**: GUI 앱과 별개로, COM3에서 2채널 데이터를 바로 CSV로 받아 적는 독립 실행 스크립트 (`C:\EMG\data`에 저장, Ctrl+C로 종료)

## 3. 2채널(schema v2) 마이그레이션

Arduino가 센서 1개(3컬럼, `time_us,env,raw`)에서 센서 2개(5컬럼, `time_us,biceps_env,biceps_raw,brachio_env,brachio_raw`)로 바뀌면서, PC 앱이 구 스키마만 받아들이도록 되어 있어 **모든 실제 데이터가 "잘못된 행"으로 거부되고 그래프가 비는 문제**가 있었다. 파서·데이터 모델(`SampleRecord`)·CSV 헤더·품질 지표·실시간 그래프·세션 뷰어·연결 패널의 핀 표시·모의 신호 생성기까지 전부 4채널 기준으로 업데이트했고, 데이터셋 `schema_version`도 `1.0.0` → `2.0.0`으로 올렸다. **구버전(1채널) 데이터셋은 이번 버전과 스키마가 달라 호환되지 않는다.**

검증: 사용자가 실제로 캡처한 시리얼 모니터 출력 10줄을 그대로 파서에 넣어 10개 전부 정상 파싱 확인, 모의 2채널 신호로 GUI 기록 → 그래프 4곡선 정상 표시 → CSV 4컬럼 정상 저장 → `validate_dataset.py` 통과까지 end-to-end로 확인.

## 4. 테스트 현황

```
pytest -q  →  33 passed
```

work order 9절의 실패 재현 시나리오(파서 오류, `micros()` 순환/재부팅, 저장 중단/복구, 장치 끊김, UI 상태 전이, 10초 모의 통합 기록)와 세션 불러오기 기능을 모두 자동화 테스트로 커버하며, 2채널 스키마에 맞춰 전부 갱신했다.

## 5. 실사용 중 발견하고 수정한 이슈

실제로 앱을 켜서 써보는 과정에서 아래 문제들이 나왔고, 전부 재현 테스트를 추가한 뒤 수정했다.

| # | 증상 | 원인 | 조치 |
|---|---|---|---|
| 1 | Windows에서 PyQt6 로드 실패(`WinError 127`) | PyQt6 6.11.x가 이 환경에서 `Qt6Core.dll` 로드 실패 | `PyQt6<6.8`(6.7.1 검증됨)로 고정 |
| 2 | 실시간 그래프가 0~45ms 구간을 반복하며 지그재그로 표시됨 | 배치(약 40ms 단위)마다 그래프 시간을 0부터 다시 계산 | 연결 시작 시점을 기준으로 계속 누적되는 시간축으로 수정 |
| 3 | 연결은 됐는데 그래프/수신률/오류 카운트가 전혀 갱신 안 됨 | 유효 샘플이 0개일 때는 진단 정보 자체가 UI로 전달되지 않던 버그 | 유효 샘플이 없어도 주기적으로 "수신 대기 중" / "유효 샘플 없음 — baud rate/포트 확인 필요" 등 상태가 갱신되도록 수정 |
| 4 | (내부 테스트 중) 모의신호 재생 속도를 500Hz에 정밀하게 맞추려고 busy-spin을 썼더니 GUI 전체가 멈춤 | 백그라운드 스레드의 busy-spin이 GIL을 과점유 | 단순 `time.sleep()` 방식으로 되돌림. 대신 화면의 수신률 표시는 실측치를 그대로 보여줘서 속도 차이를 숨기지 않음 |
| 5 | "잘못된 행"이 계속 뜨고 그래프가 아예 안 찍힘, 핀이 4개인데 2개만 표시됨 | **근본 원인**: Arduino가 2채널(5컬럼)로 바뀌었는데 PC 앱은 여전히 1채널(3컬럼) 스키마만 파싱 | 3절 내용대로 앱 전체를 2채널 스키마로 마이그레이션 |

이전 보고서에서는 3번 이슈(진단 미갱신)가 "그래프 안 보임"의 원인이라고 추정했었는데, 실제로는 5번(스키마 불일치)이 근본 원인이었다. 3번 수정 덕분에 "유효 샘플 없음 — baud rate/포트/펌웨어 확인 필요"라는 메시지가 떠서 원인을 좁히는 데는 도움이 됐다.

## 6. 알려진 제한사항 (다음 우선순위)

1. **실제 ESP32 + 2채널 센서로 장시간(1분 이상) 녹화가 끝까지 안정적인지 현장 재확인 필요.** 파서 레벨 검증은 끝났지만 GUI 풀 세션 하드웨어 테스트는 아직.
2. 모의신호 실시간 미리보기 속도가 Windows 타이머 해상도 때문에 500Hz보다 낮게 나올 수 있음(화면 표시값은 항상 실측치).
3. `writer_queue_max_size`/`overflow_count` 지표는 현재 항상 즉시 flush하는 구조라 실질적으로 채워지지 않음.
4. PyInstaller 단일 실행 파일 패키징 미구현(선택 사항).
5. 구버전(1채널) 데이터셋과의 하위 호환은 지원하지 않음(필요하면 별도 마이그레이션 스크립트 작성 필요).

## 7. 실행 방법

```powershell
# 프로젝트 루트(C:\develop\EMGDataSetController)에서
.venv\Scripts\Activate.ps1
python -m emg_collector

# 테스트
pytest -q
```

독립 2채널 로거만 쓰고 싶다면 (GUI 없이 COM3 → CSV):

```powershell
cd C:\EMG
python emg_2ch_logger.py
```

자세한 설치/데이터셋 스키마/복구 절차는 `README.md` 참고.

## 8. 다음 할 일 제안

- [ ] 실제 ESP32 + 2채널 센서로 GUI에서 최소 1분 녹화, 실측 수신률/결측률 확인
- [ ] 결과를 팀에 공유
- [ ] 필요 시 PyInstaller 패키징 검토
