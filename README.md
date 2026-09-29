# EMG Dataset Collector

ESP32 기반 근전도(EMG) 데이터셋 수집용 데스크톱 앱 (Python + PyQt6). `WorkOrder/Codex_EMG_Dataset_Collector_Work_Order.md`의 요구사항을 구현한다.

ESP32에서 `time_us,env,raw` 형식의 500 Hz CSV 스트림(460800 baud)을 받아 실시간으로 표시하고, 원본 ADC 값을 손실 없이 저장하며, 피험자/세션 메타데이터를 신호 데이터와 분리해서 관리한다. 하드웨어 없이도 모의 신호 모드로 전체 기능을 사용/테스트할 수 있다.

## 설치

Python 3.11 이상이 필요하다. **PyQt6는 6.8 이상 버전에서 일부 Windows 환경(특히 6.11.x)에서 `Qt6Core.dll` 로드가 실패하는 문제가 확인되었다** (`WinError 127`); `pyproject.toml`에서 `PyQt6<6.8`로 고정해 두었으니, 상한을 올리기 전에 반드시 해당 환경에서 재검증한다.

```bash
python -m venv .venv
```

**Windows PowerShell**:
```powershell
.venv\Scripts\Activate.ps1
```

**Git Bash**:
```bash
source .venv/Scripts/activate
```

설치 및 실행:
```bash
pip install -e ".[dev]"
python -m emg_collector
pytest -q
```

또는 `python scripts/run_app.py [--dataset-root PATH]`로 실행할 수 있다. `--dataset-root`를 지정하지 않으면 현재 폴더의 `./datasets`가 사용된다.

## 실행 방법

### 모의 신호(Mock) 모드 — 하드웨어 없이 전체 기능 사용

1. 앱 실행 후 "입력 소스"에서 **모의 EMG 신호**를 선택하고 "연결"을 누른다.
2. 피험자 정보를 입력하고 연구 동의 체크박스를 확인한다.
3. "기록 시작"으로 녹화를 시작하고, 라벨을 바꾸거나 "사용자 이벤트 표시"로 이벤트를 남길 수 있다.
4. "기록 종료 및 저장"으로 세션을 저장한다.

### ESP32 시리얼 모드

1. `firmware/emg_streamer_reference.ino`를 ESP32에 업로드한다 (핀/보드레이트를 변경하지 않는다).
2. 입력 소스를 **ESP32 시리얼**로 선택하고, "포트 새로고침"으로 `COM9` 등 실제 포트를 찾아 선택한다. **포트 번호는 예시일 뿐이며 코드에 고정된 값이 아니다.** 시스템마다 다르게 할당되므로 항상 콤보박스에서 자동 검색된 포트를 선택한다.
3. Baud rate는 기본값 `460800`을 사용한다.
4. "연결" 후 나머지 절차는 모의 신호 모드와 동일하다.

## 생성되는 데이터셋

저장 경로 예시 (기본 `./datasets`, UI에서 "저장 폴더 열기"로 확인 가능):

```text
datasets/
├─ dataset_manifest.json         # schema_version 등 메타
├─ participants_private.csv      # participant_id,name,created_at_utc (식별정보; 내보내기에서 제외)
├─ participants_public.csv       # 비식별 피험자 메타데이터
├─ sessions.csv                  # 세션 1행 = 1레코드, status: complete/incomplete/recovered
└─ sessions/<SESSION_ID>/
   ├─ samples.csv   # sample_index,device_time_us,device_time_us_unwrapped,elapsed_s,host_elapsed_s,env_adc,raw_adc,label
   ├─ events.csv    # event_index,sample_index,device_time_us_unwrapped,elapsed_s,event_type,label,note
   ├─ metadata.json # 세션/장치/방식/펌웨어 규격 스냅샷
   └─ quality.json  # 수신률, 오류/결측 추정치, 클리핑 비율 등
```

스키마 버전은 `dataset_manifest.json`과 각 `metadata.json`의 `schema_version` 필드에 기록된다.

내보내기: `emg_collector.storage.exporter.export_deidentified(dataset_root, output_dir)`로 `participants_private.csv`를 제외한 비식별 데이터셋을 복사한다.

검증: 데이터셋 참조 무결성(세션-ID 일치, 파일 존재, 스키마 일치, 유효 샘플 수 일치, `.part` 잔존 여부, 시간 단조성)을 다음으로 확인한다.

```bash
python scripts/validate_dataset.py datasets
```

## 결측 샘플 추정 방식

보정된(unwrap된) ESP32 시간 간격이 목표 간격(`2000 us`)의 1.5배를 초과하면 gap으로 카운트하고, `round(간격/2000) - 1`만큼 샘플이 누락된 것으로 추정한다. 이는 **추정치**이며 실제 시리얼/무선 손실과 ESP32 스케줄링 지연을 완전히 구분하지 못한다 (`quality.json`의 `estimated_missing_samples_method` 필드에도 동일하게 명시).

## 복구 (비정상 종료)

기록 중 앱이 비정상 종료되면 `sessions/<ID>/samples.csv.part`, `events.csv.part`가 남는다. 다음 실행 시 자동으로 감지되어 복구 여부를 묻는다("예" 선택 시 flush + fsync 후 `.csv`로 원자적 이름 변경, `status=recovered`). `.part` 파일은 사용자가 명시적으로 복구하기 전까지 삭제되지 않는다.

## 테스트

```bash
pytest -q
```

`tests/`는 work order 9절의 실패 재현 시나리오를 따른다: 파서 오류(9.1), `micros()` 순환/재부팅 구분(9.2), 저장 중단/복구(9.3), 장치 끊김(9.4), UI 상태 전이(9.5), 10초 모의 통합 기록(9.6).

## 알려진 제한사항

- **실제 ESP32 하드웨어로 검증하지 않았다.** 이 구현은 Mock 모드로만 검증되었으며, 실제 장치의 시리얼 타이밍/노이즈 특성은 다를 수 있다. 실 장치 연결 전에는 "검증됨"으로 간주하지 않는다.
- 모의 신호 모드의 실시간(UI 미리보기) 재생 속도는 Windows의 `time.sleep()` 타이머 해상도와 Python 인터프리터 오버헤드로 인해 설정값(500 Hz)보다 낮게 관측될 수 있다 (화면의 수신률 표시는 실측값을 그대로 보여주며 과장하지 않는다). 이는 실시간 미리보기 스트림에만 해당하며, `tests/test_mock_recording.py`의 10초 통합 테스트처럼 실시간 대기 없이 구동하는 경로와 실제 ESP32 하드웨어 경로에는 영향이 없다.
  - 참고: 샘플마다 마지막 ~1ms를 busy-spin으로 정밀 대기하는 방식을 시도했으나, Qt 스레드 환경에서 GIL을 심하게 점유해 GUI 스레드 전체가 멈추는 문제가 실제로 재현되어 되돌렸다. 정밀도보다 응답성을 우선했다.
- writer queue 관련 지표(`writer_queue_max_size`, `writer_queue_overflow_count`)는 `quality.json`에 필드는 존재하나, 현재 구현은 배치를 즉시 CSV에 flush하는 방식이라 상시 채워지지 않는다. 향후 유계 큐를 SerialWorker와 SessionWriter 사이에 명시적으로 두면 실제 사용량을 채울 수 있다.
- PyInstaller 기반 단일 실행 파일 패키징은 아직 구현하지 않았다 (work order 12.3, 선택 사항).
