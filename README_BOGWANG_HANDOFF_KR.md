# 보광 전달용 SCLAS 프로젝트 안내

이 압축본은 SCLAS 해저 케이블 CAE 분석 GUI와 Abaqus 연동 작업을 이어받기 위한
Windows용 전달 패키지입니다.

## 현재까지 완료된 상태

- Windows Visual Studio 솔루션 추가 완료
- GUI 실행 배치파일 준비 완료
- GUI 메인 화면/UI 개선 완료
- GUI에서 Abaqus job package 생성 가능
- placeholder `abaqus_runner.py`가 `result_data.csv`와 `result_summary.json` 생성 가능
- Abaqus/CAE에서 실행할 경우 `.cae`, `.inp` mesh scaffold 생성 시도 가능
- 로컬 상태 점검용 `run_self_check.bat` 추가 완료

## 먼저 실행해볼 것

압축을 푼 뒤 프로젝트 폴더에서 아래 순서로 확인하면 됩니다.

```bat
setup_windows.bat
run_self_check.bat
run_sclas.bat
```

Visual Studio를 사용할 경우:

```text
SCLAS-cable-analysis.sln
```

위 솔루션 파일을 열면 됩니다.

## 핵심 파일

```text
code/sclas_remote_gui.py
```

메인 GUI입니다. 사용자가 geometry, material, mesh, analysis 조건을 입력하고
job package를 생성합니다.

```text
code/abaqus_runner.py
```

Abaqus 연동 핵심 파일입니다. 현재는 placeholder 해석 결과와 mesh scaffold를
만드는 단계입니다. 실제 Abaqus 해석을 붙일 때는 이 파일을 중심으로 수정하면 됩니다.

```text
docs/ABAQUS_BACKEND_IMPLEMENTATION_PLAN_KR.md
```

Abaqus 백엔드 구현 순서를 한국어로 정리한 문서입니다. 먼저 이 파일을 읽는 것을
추천합니다.

## GUI와 Abaqus의 약속

GUI는 job 폴더를 만들고 그 안에 다음 파일들을 생성합니다.

```text
input_data.json
units_manifest.json
BACKEND_CONTRACT.md
abaqus_runner.py
```

Abaqus 백엔드는 같은 job 폴더 안에 반드시 아래 파일을 만들어야 합니다.

```text
result_data.csv
```

CSV header는 반드시 아래와 같아야 합니다.

```csv
curvature_1_per_m,moment_kn_m
```

이 header가 바뀌면 GUI가 결과를 읽지 못합니다.

추가적인 결과 지표는 아래 파일에 넣으면 됩니다.

```text
result_summary.json
```

예를 들어 contact pressure, slip displacement, torsional stiffness,
bird-caging risk 같은 값은 `result_summary.json`에 저장하는 방식입니다.

## Abaqus 실행 예시

GUI가 만든 job 폴더 안에서 아래처럼 실행합니다.

```bat
abaqus cae noGUI=abaqus_runner.py -- input_data.json
```

현재 `abaqus_runner.py`는 Abaqus API가 있는 환경에서 실행되면 mesh scaffold를 만들고,
정상 Python에서 실행되면 placeholder 결과를 만듭니다.

## 보광이가 이어서 할 일

1. GUI에서 job package 생성
2. 생성된 `input_data.json` 구조 확인
3. Abaqus에서 `abaqus_runner.py` 실행
4. 생성된 `.cae`, `.inp` mesh scaffold 검증
5. armour / sheath / bedding 사이 contact-friction 정의
6. cyclic bending boundary condition 추가
7. Abaqus solve 실행
8. ODB에서 moment-curvature 결과 추출
9. `result_data.csv` 생성
10. 부가 지표를 `result_summary.json`에 저장

## 압축본에서 제외한 것

아래 항목들은 로컬/개인/대용량 자료라 압축본에서 제외했습니다.

```text
.git/
.venv/
.venv_broken_20260611/
jobs/
local_notes/
references/
settings.json
__pycache__/
```

논문 PDF나 ZeroTier 안내 자료는 `references/`, `local_notes/`에 있었기 때문에
필요하면 별도로 전달해야 합니다.
