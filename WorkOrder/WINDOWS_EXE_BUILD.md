# Windows 실행 파일 — 2026-10-26

산출물: `dist/EMGController.exe` (단일 파일, 185,502,309 bytes, 약 177 MiB).
SHA-256: `57906f0cf1ac329152caf3fb25b2aa74809bb57ab7560aefc446332b0289b769`.

저장소의 `dist/EMGController.exe`는 Git LFS로 관리한다. 복제 후 `git lfs pull`로 실제 바이너리를 받는다.
다른 dist 산출물·수집 데이터·영상·가상환경·모델 원본은 Git 제외를 유지한다.

Python 설치나 별도 모델 다운로드 없이 더블클릭한다. 수집 데이터는 실행 파일 옆의
`datasets` 폴더에 저장된다. 쓰기 가능한 폴더에 실행 파일을 둔다.
기존 Python 실행 방식의 `./datasets` 기본값은 유지했다.
MediaPipe Pose Lite 모델과 PILOT 프로토콜을 포함하며 실제 참가자 자료는 포함하지 않았다.
기본 화면은 **이두·삼두 EMG + MediaPipe 동시 측정·자동 라벨링**이다.
원본 데이터와 `labeled_samples.csv`를 함께 저장하며, 기존 v2 화면은 `--legacy-v2`로만 연다.

## 실제 검증

* 소스 회귀 시험: **81 passed in 14.94s**.
* 실행 파일 자체 self-test: exit **0**, `ok=true`.
* 다른 작업 폴더에서 PATH를 Windows/System32로 제한하고 PYTHONHOME/PYTHONPATH를 제거한 실행:
  exit **0**, `ok=true`. Python 환경 경로를 사용하지 않고 실행됐다.
* 포함 모델 해시 확인 및 실제 MediaPipe 빈 이미지 추론 성공.
* Qt 메인 창, v3 수집 창, 영상/EMG/각도 검토 창 생성 성공.
* 독립 실행 점검: synthetic EMG **493 samples**, MJPG 영상 **23 frames**, MediaPipe 통합 라벨 **493행**, dataset validator 오류 없음.
* 기본 화면 유형 `biceps_triceps_mediapipe`와 두 EMG 채널의 MediaPipe 라벨 연결을 exe 자체에서 검사했다.
* 수집·검토 창의 800×600 크기와 종료 사유 전체 한국어 선택지 검사 통과:
  `compact_collection_and_review=true`, `korean_termination_choices=true`.
* 소스에서는 640×480/800×600, 반복 확대/축소 시 영상 비율·중지 버튼 위치·스크롤·동의 문구 클릭도 검사했다.
  맑은 고딕으로 수집·검토 640×480 화면을 추가 확인했다. 다중 모니터·고배율 DPI 조합은 별도 검증하지 않았다.
* 실제 센서·카메라 연결은 검증하지 않았다. v3는 기존과 같이 PILOT 단계다.

원본 점검 결과: `build/windows-self-test.json`, `build/portable-self-test.json`.
빌드 로그: `build_windows.log` (모두 Git 제외).

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
