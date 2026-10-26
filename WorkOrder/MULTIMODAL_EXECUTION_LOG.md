# 실행 로그 — 2026-10-26 KST

시작 HEAD: `58f8d4ab5135e2251b794cdeba54bb60cf4121db` (지시서 기준과 동일).
시작 시 사용자 파일: 미추적 `WorkOrder/EMGController_Multimodal_Collection_Work_Order.md`; 보존.
제공된 최신 AGENTS 지침: 이전 세션 없음. 별도 위임 지시 없음.

수정 전 Python 3.12.8 기본 환경:

* `python -m pytest -q`: import 경로 오류 7개.
* `PYTHONPATH=src python -m pytest -q`: pyserial 미설치로 UI 수집 오류 1개.
* UI 제외 기존 시험: **24 passed**.
* 저장소 `.venv`에 pyserial 설치 후 기존 전체 시험: **33 passed in 2.93s**.
* 지시서 3절의 6개 fixture 추가 후 실행: 신규 multimodal 모듈 미구현으로 collection error (예상 실패).

기본 환경은 변경하지 않았다. 최초 `.venv --system-site-packages` 설치에서는
호스트의 opencv-python 5/NumPy 2, protobuf 관련 패키지 충돌 경고가 있었음.
최종 검증 환경과 결과는 PROGRESS_REPORT.md에 기록한다.

## 최종 실행 결과

* `.venv/Scripts/python -m pytest -q`: **67 passed in 9.38s**. 출력은 `MULTIMODAL_TEST_RESULTS.txt`.
* `scripts/create_synthetic_dataset.py datasets/synthetic_20261026`: 정상 생성.
* `scripts/validate_dataset.py datasets/synthetic_20261026`: integrity checks 통과.
* `scripts/export_training_dataset.py ... --synthetic --allow-pilot`: 고정 시간 window 15개.
* 같은 입력 `--last-k 3 --stride-reps 2`: 8개.
* 존재하지 않는 dataset validator 음성 검사: exit code **1**, 누락 필드 3개 출력.
* 신규 코드 `ruff --select F`: 통과. `compileall`, `git diff --check`: 통과.
* editable 패키지 설치: 성공. Qt offscreen 메인 창 실제 생성/이벤트 루프/종료: exit **0**.
* MediaPipe 실제 Tasks API 모델 생성·640×480 blank inference: 성공, 예상대로 landmark 0.
* 실제 카메라 0 open/read: 실패. ESP32는 식별·연결하지 않았음. 실장치 파일럿 미검증.

## 변경 파일과 목적

| 경로 | 목적 |
|---|---|
| `multimodal/schema.py`, `controller.py`, `validator.py` | v3 schema·채널·동의·세트/시도·worker 조율·무결성 |
| `acquisition/camera_worker.py`, `pose/*`, `sync/*` | 카메라/MJPG/프레임 mapping·MediaPipe·각도·epoch 회귀 |
| `protocols/*`, `labeling/*` | PILOT 기준·반복 상태기계·검토 chain·잔여 라벨·검토 일치도 |
| `storage/multimodal_writer.py`, `training_export.py`, `exporter.py` | 유계 저장·manifest·원본 보존 복구·causal export·allowlist |
| `ui/multimodal_panel.py`, `multimodal_review.py`, 기존 `main_window.py`/`session_viewer.py` | 기존 PyQt 안의 수집/검토·v2/v3 라우팅 |
| 기존 `models.py`, `participant_form.py`, `dataset_store.py` | 익명 등록·0/결측·운동 경력·혼합 버전/복구 인식 |
| 기존 `acquisition/parser.py`, `serial_worker.py` | uint32 검증·legacy 창의 신규 헤더 거절 |
| `scripts/{create_synthetic_dataset,download_pose_model,export_training_dataset,validate_dataset}.py` | 예제·설치·검증·학습 export CLI |
| 신규 `firmware/emg_streamer_biceps_triceps_v3.ino` | 고정 핀의 별도 이두·삼두 헤더; 기존 reference 보존 |
| `tests/test_multimodal*.py`, `test_parser_failures.py`, `test_ui_state.py` | 실패/통합·새 익명 등록 규칙·기존 회귀 |
| `pyproject.toml`, `.gitignore`, `README.md`, `PROGRESS_REPORT.md`, 본 문서들 | 고정 optional 의존성·민감자료 제외·인계 |

데이터 사전과 사용법은 `MULTIMODAL_V3_SCHEMA.md`, `MULTIMODAL_V3_GUIDE.md`.
프로토콜 파일은 `unilateral_curl_pilot.json` (0.1.0 PILOT), 데이터 스키마는 3.0.0.
현재 자동 시험 실패 없음. 하드웨어·본 수집 준비 상태는 PROGRESS_REPORT의 미검증 TODO 참조.

## 추가 실행 — 이두·삼두와 MediaPipe 동시 라벨링

기본 진입을 멀티모달 화면으로 변경. 원본 수집 종료 후 `labeled_samples.csv` 생성 및
manifest/validator 검증, 검토 revision의 새 CSV export를 추가했다.
소스 시험 실제 결과: **76 passed in 11.69s**.
`datasets/simultaneous_20261026`: 24,001행 통합 라벨, dataset validator 통과.
재빌드 exe의 독립 self-test: exit 0, EMG 502행·영상 26프레임·통합 라벨 502행, 오류 없음.
원본 결과 JSON은 `build/portable-self-test.json`, 상세 변경/한계는 PROGRESS_REPORT 최신 절.

## 추가 실행 — 화면 크기 조절·종료 사유 한국어

수집/검토 창의 최소화·최대화·크기 조절, 드래그 패널·스크롤, 영상 비율 조절,
하단 고정 중지 버튼, 동의 문구 줄바꿈을 추가했다. 종료 사유 8개는 한국어로 표시하고 기존 저장 ID는 유지한다.
`pytest -q`: **81 passed in 14.94s**.
새 exe의 독립 self-test exit 0, `compact_collection_and_review=true`, `korean_termination_choices=true`,
EMG/라벨 493행·영상 23프레임, validator 오류 없음.
맑은 고딕으로 640×480 수집/검토 화면도 별도 확인했다. 고배율·다중 모니터 조합은 미검증.
