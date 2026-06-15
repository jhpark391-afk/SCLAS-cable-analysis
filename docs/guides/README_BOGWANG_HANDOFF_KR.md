# 보광 전달용 HELIX 백엔드 안내

이 저장소는 HELIX 해저 케이블 CAE 분석 GUI와 Abaqus 백엔드 연동 작업을 위한 프로젝트입니다.

HELIX = **Helical Element Localised Interaction eXamination**

## 제일 먼저 볼 문서

아래 문서가 최신 백엔드 전달 문서입니다.

```text
docs/HELIX_BACKEND_HANDOFF_BOGWANG_KR.md
```

그 다음 구현 순서를 더 자세히 보려면:

```text
docs/ABAQUS_BACKEND_IMPLEMENTATION_PLAN_KR.md
```

전체 GUI/프로젝트 흐름은:

```text
README_SCLAS_WORKFLOW.md
```

## Windows에서 먼저 실행

```bat
setup_windows.bat
run_self_check.bat
run_sclas.bat
```

Visual Studio를 쓸 경우:

```text
SCLAS-cable-analysis.sln
```

## 백엔드 핵심 파일

```text
code/abaqus_runner.py
```

Abaqus 연동 핵심 파일입니다. 현재는 mesh scaffold와 placeholder 결과를 만드는 단계입니다. 실제 작업은 이 파일을 중심으로 contact, bending boundary condition, solve, ODB extraction을 추가하면 됩니다.

```text
code/sclas_remote_gui.py
```

GUI 메인 파일입니다. 사용자가 geometry/material/mesh/analysis 조건을 입력하고 job package를 생성합니다.

## GUI가 만드는 job package

GUI의 `Analysis` 탭에서 `Export job package only`를 선택하고 `Run / Create Job`을 누르면 아래 폴더에 job이 생성됩니다.

```text
jobs/SCLAS_jobs/job_YYYYMMDD_HHMMSS_xxxxxxxx/
```

GUI가 생성하는 파일:

```text
input_data.json
units_manifest.json
BACKEND_CONTRACT.md
abaqus_runner.py
```

백엔드는 같은 폴더에 아래 파일을 만들어야 합니다.

```text
result_data.csv
result_summary.json
```

필수 CSV header:

```csv
curvature_1_per_m,moment_kn_m
```

이 header는 GUI가 결과 그래프를 읽는 계약이므로 바꾸면 안 됩니다.

## Abaqus 실행 예시

job 폴더 안에서:

```bat
abaqus cae noGUI=abaqus_runner.py -- input_data.json
```

## 이번 전달 패키지에 포함된 참고 이미지

GUI 화면 확인용 캡처입니다.

```text
screenshots/gui/helix_gui_01_design.png
screenshots/gui/helix_gui_02_mesh.png
screenshots/gui/helix_gui_03_analysis.png
screenshots/gui/helix_gui_screenshots.zip
```

## 보광이가 제일 먼저 할 일

1. `docs/HELIX_BACKEND_HANDOFF_BOGWANG_KR.md` 읽기
2. GUI에서 job package 하나 생성
3. job 폴더의 `input_data.json` 확인
4. Abaqus에서 `abaqus_runner.py` 실행
5. `.cae`, `.inp` mesh scaffold 확인
6. contact/friction pair 추가
7. cyclic bending boundary condition 추가
8. ODB에서 moment-curvature 추출
9. `result_data.csv`와 `result_summary.json` 생성
10. GUI에서 `Load result CSV` 또는 `Compare CSV`로 확인
