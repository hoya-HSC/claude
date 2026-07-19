# photomanager

데스크탑에 있는 사진/동영상을 **인물 / 장소 / 이벤트(여행)** 기준으로 분류하는 로컬 전용 도구입니다.

## 설계 원칙 (논의된 요구사항 요약)

- **원본 파일 불변**: 파일을 이동·rename하지 않습니다. 분류 결과는 SQLite DB의 메타데이터/태그로만 존재하고, 실제 브라우징은 웹 검수 UI로 합니다.
- **해시 기반 식별**: 파일은 경로가 아니라 내용 해시로 식별합니다. 파일 위치가 바뀌어도(같은 볼륨 내 이동, 외장하드 드라이브 문자 변경 등) 재처리 없이 경로만 갱신됩니다.
- **증분 처리**: 재실행 시 새 파일/변경된 파일만 처리합니다. 전체 재실행이 필요 없습니다.
- **장소는 GPS 한정**: EXIF GPS가 없는 파일은 장소를 추정하지 않고 공란으로 둡니다(이미지 기반 장소 추정은 오류율이 높아 채택하지 않음).
- **인물은 반자동 검수**: 얼굴 임베딩으로 자동 군집화하되, 애매한 것만 사람이 웹 UI에서 확인/이름 지정 → 확정된 라벨이 다음 인식 정확도를 높이는 구조.
- **외장하드 지원**: 드라이브 문자가 아니라 볼륨 고유 ID로 식별하므로, 연결 안 된 하드의 파일을 "삭제됨"으로 오판하지 않습니다.

## 실행 환경

이 저장소의 코드는 클라우드 환경에서 작성되었고, **실제 실행(스캔/얼굴인식/GPU 연산)은 사용자의 데스크탑 PC(Windows, RTX 3080, i7)에서** 합니다. 여기서는 GPU 없이도 검증 가능한 로직(스캐너, 이벤트 클러스터링, DB 스키마 등)만 유닛 테스트로 확인했습니다.

## PC 사전 설치

1. **NVIDIA 그래픽 드라이버**가 최신인지 확인 (Windows가 3080으로 화면을 띄우고 있다면 대부분 이미 설치됨)
2. **Miniconda 설치**: https://docs.conda.io/en/latest/miniconda.html
   - CUDA Toolkit을 시스템에 별도로 설치할 필요 없습니다. conda 환경 안에 격리된 `cudatoolkit`/`cudnn`을 설치하므로 관리자 권한/재부팅이 필요 없습니다.
3. **ffmpeg**: conda 환경 생성 시 함께 설치됩니다(동영상 메타데이터/프레임 추출용).

## 환경 설정

PowerShell에서 저장소 루트로 이동한 뒤:

```powershell
.\setup\setup_windows.ps1
```

이 스크립트가 하는 일:
1. `nvidia-smi`로 드라이버 확인
2. conda 설치 여부 확인
3. `setup/environment.yml`로 `photomanager` conda 환경 생성/갱신 (cudatoolkit, cudnn, ffmpeg, 파이썬 의존성 전부 포함)
4. `setup/check_gpu.py`로 onnxruntime이 실제로 GPU(CUDAExecutionProvider)를 잡는지 검증

실패하면 스크립트가 원인(드라이버 없음/conda 없음/CUDA-cuDNN 버전 불일치)을 출력합니다.

## 사용법

환경 활성화:

```powershell
conda activate photomanager
```

### 0. (선택) 날짜 폴더로 정리: `organize`

규칙 없이 쌓인 파일을 `YYYY-MM-DD` 폴더로 정리합니다. 촬영자/소스별로
폴더를 나눠 두셨다면 그 폴더 하나씩 실행하세요. 날짜는 **사진 EXIF /
동영상 메타 → 파일명 날짜 → 파일 수정시간** 순으로 결정합니다.

```powershell
# 먼저 미리보기 (실제로 안 옮김) - 어떻게 이동될지 확인
photomanager organize "F:\00. image\정리안된폴더"

# 확인 후 실제 이동
photomanager organize "F:\00. image\정리안된폴더" --apply
```

안전장치:
- `--apply` 없으면 **미리보기만** 하고 파일을 건드리지 않습니다.
- 같은 날짜 폴더에 **같은 이름 파일**이 오면, 내용이 같으면 중복으로
  건너뛰고, 다르면 ` (1)` 을 붙여 **기존 파일을 덮어쓰지 않습니다**.
- 원본 사진에는 어떤 메타데이터도 쓰지 않습니다(이동만).

#### GUI로 쓰기 (명령어 없이)

같은 기능을 창 하나로 쓸 수 있는 GUI도 있습니다. 폴더 선택 → 미리보기 →
확인 버튼 순서로, 명령어를 칠 필요가 없습니다. 추가 라이브러리 설치도
필요 없습니다 (Tkinter는 파이썬 기본 내장).

```powershell
photomanager-organize-gui
```

이 GUI 자체는 리소스를 거의 쓰지 않습니다 — 창을 띄우는 것뿐이고, 실제
스캔 작업(디스크 읽기)은 명령어로 실행할 때와 동일합니다.

**바탕화면에서 더블클릭으로 실행하려면**, 아래 내용을 메모장에 붙여넣고
"모든 파일" 형식으로 `사진정리.bat` 이름으로 바탕화면에 저장하세요:

```bat
@echo off
call C:\Users\%USERNAME%\miniconda3\Scripts\activate.bat
call conda activate photomanager
start "" photomanager-organize-gui
```

정리 후 파일 위치가 바뀌어도, 아래 `run` 스캔은 **내용 해시로 식별**하므로
얼굴 인식 등을 다시 하지 않고 경로만 갱신합니다.

한 배치 실행 (스캔 → 메타데이터 추출 → 얼굴 인식 → 이벤트 재계산, `batch_size`만큼만 처리하고 종료):

```powershell
photomanager run --roots "D:\Photos" "E:\Videos"
```

며칠에 걸쳐 나눠서 처리하려면 같은 명령을 반복 실행하면 됩니다 — 이미 처리된 파일은 자동으로 건너뜁니다.

검수 웹 UI 실행:

```powershell
photomanager serve
```

브라우저에서 `http://127.0.0.1:8000` 접속 → 자동으로 묶인 얼굴 군집을 보고 이름을 입력해 확정합니다.

## 프로젝트 구조

```
src/photomanager/
  config.py       배치 크기, 임계값 등 설정
  db.py           SQLite 스키마
  volume.py       볼륨(드라이브) 고유 ID 식별
  scanner.py      해시 기반 증분 파일 스캔
  metadata.py     EXIF/ffprobe로 촬영일시·GPS 추출
  geocode.py      GPS -> 장소 (오프라인 역지오코딩, GPS 없으면 NULL)
  events.py       시간/GPS 간격 기반 여행·이벤트 클러스터링
  faces.py        InsightFace 얼굴 검출/임베딩 (GPU)
  clustering.py   인물 자동 매칭 + 미분류 얼굴 군집 제안(HDBSCAN)
  video.py        동영상 씬컷 기반 키프레임 추출
  pipeline.py     위 단계를 체크포인트 방식으로 묶는 오케스트레이터
  cli.py          `photomanager run` / `photomanager serve`
  web/app.py      검수용 FastAPI 웹 UI
```

## 테스트

GPU/실제 사진 없이도 확인 가능한 부분만 이 환경에서 테스트했습니다:

```bash
pip install -e ".[dev]" --no-deps  # GPU 패키지 설치 없이 개발용 최소 설치
pytest tests/
```
