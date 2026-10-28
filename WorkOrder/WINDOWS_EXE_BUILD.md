# Windows 실행 파일 — 2026-10-28

최신 재빌드: MediaPipe 각도 통합 저장 수정 포함.
`dist/EMGController.exe`: 176,343,201 bytes.
SHA-256: `aaddab2295faf7d31ef42d33679c7fdbf96721d95a13ed636bfe679c6ae4cb06`.

자체 검사 `ok=true`: EMG/통합 라벨 501행, 영상 22프레임, validator 오류 0.
Python 경로 제거·다른 작업 폴더 독립 실행: exit 0, `ok=true`,
EMG/통합 라벨 493행, 영상 22프레임, validator 오류 0.
Anaconda 기반 가상환경의 표준 라이브러리 DLL 누락을 빌드 spec에서 보완했다.
검사 지연 시 원인을 확인하도록 자체 검사 보고서에 진행 단계를 기록한다.
실제 센서·카메라 입력은 검증하지 않았다.

아래는 이전 빌드 기록이다.

산출물: `dist/EMGController.exe` (이름 입력·동의 체크·단회 측정 + 덤벨 무게/개수 + F1~F6 수정 포함, 단일 파일, 185,544,261 bytes, 약 177 MiB).
SHA-256: `715a1a224077dd73ceacbd27496ca6b58887de9958aba6dd5c3565309b957ef0`.

저장소의 `dist/EMGController.exe`는 Git LFS로 관리한다. 복제 후 `git lfs pull`로 실제 바이너리를 받는다.
다른 dist 산출물·수집 데이터·영상·가상환경·모델 원본은 Git 제외를 유지한다.

Python 설치나 별도 모델 다운로드 없이 더블클릭한다. 수집 데이터는 실행 파일 옆의
`datasets` 폴더에 저장된다. 쓰기 가능한 폴더에 실행 파일을 둔다.
기존 Python 실행 방식의 `./datasets` 기본값은 유지했다.
MediaPipe Pose Lite 모델과 PILOT 프로토콜을 포함하며 실제 참가자 자료는 포함하지 않았다.
기본 화면은 **이두·삼두 EMG + MediaPipe 동시 측정·자동 라벨링**이다.
원본 데이터와 `labeled_samples.csv`를 함께 저장하며, 기존 v2 화면은 `--legacy-v2`로만 연다.

## 실제 검증

* 소스 회귀 시험: **121 passed in 41.30s**. 단회 시작/종료·동의 체크 4개·이름 비공개 저장·덤벨 무게/개수·기존 기록 호환·중량 포함 export 시험 포함. [코드 리뷰 수정 보고](CODE_REVIEW_FIX_REPORT.md).
* 실행 파일 자체 self-test: exit **0**, `ok=true`.
* 다른 작업 폴더에서 PATH를 Windows/System32로 제한하고 PYTHONHOME/PYTHONPATH를 제거한 실행:
  exit **0**, `ok=true`. Python 환경 경로를 사용하지 않고 실행됐다.
* 포함 모델 해시 확인 및 실제 MediaPipe 빈 이미지 추론 성공.
* Qt 메인 창, v3 수집 창, 영상/EMG/각도 검토 창 생성 성공.
* 최신 재빌드 자체 점검: synthetic EMG **501 samples**, MJPG 영상 **20 frames**, MediaPipe 통합 라벨 **501행**, dataset validator 오류 없음.
* 기본 화면 유형 `biceps_triceps_mediapipe`와 두 EMG 채널의 MediaPipe 라벨 연결을 exe 자체에서 검사했다.
* 수집·검토 창의 800×600 크기와 종료 사유 전체 한국어 선택지 검사 통과:
  `compact_collection_and_review=true`, `korean_termination_choices=true`.
* 소스에서는 640×480/800×600, 반복 확대/축소 시 영상 비율·중지 버튼 위치·스크롤·동의 문구 클릭도 검사했다.
  맑은 고딕으로 수집·검토 640×480 화면을 추가 확인했다. 다중 모니터·고배율 DPI 조합은 별도 검증하지 않았다.
* 실제 센서·카메라 연결은 검증하지 않았다. v3는 기존과 같이 PILOT 단계다.

원본 점검 결과: `build/windows-self-test.json`, `build/portable-self-test.json`.
빌드 로그: `build_windows.log` (모두 Git 제외).
덤벨 입력 수정 전 버전의 Python 경로 제거 독립 실행은 첫 시도에
worker_shutdown_timeout과 camera_failure(writer closed)로 실패했고, 동일 바이너리·동일
조건 재실행은 exit0/ok=true였다. 단발 종료 지연의 원인은 확정하지 않았다.
첫 실패 로그는 build/minimal_ui_portable_first_failure.json에 보존했다.
덤벨 입력 수정 후 첫 재빌드 자체 시험은 writer_shutdown_timeout으로 실패했다
(build/dumbbell_first_exe_failure.json). 점검용 synthetic 세션에만 종료 대기 20초와
전체 완료 대기 45초를 적용한 최신 EXE 자체 시험은 exit0/ok=true였다.
실제 수집 기본 watchdog의 종료 대기 5초는 유지한다. 자체 시험은 물리 지연/성능 검증이 아니다.
덤벨 입력 수정 버전의 Python 경로 제거·다른 작업 폴더 독립 실행도 exit0/ok=true였다:
EMG/통합 라벨492행·영상21프레임, validator 오류0.
이름/단회 측정 버전은 새로 재빌드했으며 자체 시험 exit0/ok=true다.
동일 최신 버전의 Python 경로 제거 독립 실행도 exit0/ok=true:
EMG/통합 라벨508행·영상19프레임, validator 오류0.
실제 센서 입력·물리 정렬 검증은 수행하지 않았고, software receive fit은 미검증으로 유지한다.

## 빌드 재현

```powershell
.venv\Scripts\python -m pip install -e ".[build,multimodal]"
# models/pose_landmarker_lite.task가 없을 때만 실행
.venv\Scripts\python scripts/download_pose_model.py
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_windows.ps1
```

빌드 스크립트는 exe 생성 후 포함된 `--self-test`를 실행하며 실패하면 오류를 반환한다.
`EMGController.spec`는 모델·native library를 묶고 사용하지 않는 대규모 학습/노트북 스택을 제외한다.
`runtime_paths.py`는 임시 추출된 읽기 전용 모델과 exe 옆의 영구 데이터 경로를 분리한다.

빌드 도구: PyInstaller 6.10.0, hooks-contrib 2026.2, pefile 2023.2.7.
처음에는 pefile 2024.8.26의 파일 분석 성능 문제로 지연되어 검증된 버전으로 고정했다.
첫 exe 점검에서는 Qt 패키지의 CRT 14.26과 Python의 CRT 14.42가 혼재해
MediaPipe native DLL 초기화가 실패했다. spec에서 수집한 CRT 사본을 Python 기반 환경의
동일 버전으로 맞춘 뒤 두 차례 exe 점검이 통과했다.
