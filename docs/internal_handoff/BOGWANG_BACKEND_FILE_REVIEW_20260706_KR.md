# 보광 백엔드 인수인계: 필요한 결과 파일과 현재까지 한 일

작성일: 2026-07-06 KST  
프로젝트 경로: `C:\Users\user\Documents\SCLAS-cable-analysis`

## 1. 핵심 요약

현재 GUI/연동 쪽에서 할 수 있는 작업은 대부분 끝났습니다.

지금 남은 핵심 병목은 보광 백엔드 쪽에서 Abaqus 모델을 실제로 끝까지 돌려서, ODB 기반 결과 파일을 GUI가 읽을 수 있는 형태로 넘겨주는 것입니다.

중요한 점은 `.cae`나 `.inp`만 있으면 아직 부족하다는 것입니다. GUI와 진단기는 Abaqus가 실제로 해석을 완료했고, 그 ODB에서 결과를 추출했다는 증거 파일을 함께 받아야 합니다.

## 2. 보광이가 넘겨줘야 하는 자료

보광이가 넘겨줘야 하는 최소 단위는 하나의 job folder입니다.

권장 구조:

```text
job_folder/
├─ input_data.json
├─ abaqus_mesh_manifest.json
├─ Cable_Bending.inp
├─ Cable_Bending.odb
├─ Cable_Bending.dat
├─ Cable_Bending.msg
├─ Cable_Bending.sta
├─ result_data.csv
├─ result_summary.json
└─ odb_extraction_summary.json
```

각 파일의 의미는 아래와 같습니다.

### `input_data.json`

GUI에서 넘어간 입력값 또는 백엔드가 실제 사용한 입력값입니다.

포함되어야 하는 주요 범위:

```text
geometry_mm
derived_geometry_mm
armour
materials
mesh
analysis_conditions
solver
output_requests
modeling
```

즉 기하, 재료, 메시, 압력, 굽힘, 마찰계수, solver 조건이 들어 있어야 합니다.

### `abaqus_mesh_manifest.json`

Abaqus 모델과 메시 생성 상태를 설명하는 파일입니다.

기록하면 좋은 항목:

```text
생성된 .inp/.cae 파일명
메시 생성 성공 여부
part/layer 구성
contact pair 개수
boundary condition 요약
사용한 mesh divisions
경고 또는 fallback 여부
```

### `Cable_Bending.inp`

Abaqus solver에 실제로 들어간 입력 deck입니다.

문제가 생기면 여기서 아래 항목을 확인합니다.

```text
*Coupling
*Equation
*Boundary
*Tie
*Contact
*Surface
*Output
```

### `Cable_Bending.odb`

가장 중요한 Abaqus 결과 원본입니다.

해석이 실제로 돌아야 생성되며, 변위, 반력, 모멘트, 응력, 접촉압 등이 들어 있습니다.

### `Cable_Bending.dat`, `.msg`, `.sta`

해석 로그입니다.

확인 목적:

```text
job completed 여부
fatal error 여부
warning 개수
increment 진행 상태
수렴 실패 위치
constraint/contact 오류
```

### `result_data.csv`

GUI가 그래프로 그릴 수 있게 ODB에서 추출한 결과표입니다.

최소 예시:

```csv
curvature_1_per_m,moment_kn_m
-0.08,-1.23
-0.04,-0.62
0,0.01
0.04,0.64
0.08,1.25
```

아래처럼 한 줄짜리 `0,0`만 있으면 실제 결과가 아니라 placeholder입니다.

```csv
curvature_1_per_m,moment_kn_m
0,0
```

### `result_summary.json`

GUI와 진단기가 결과 상태를 판단하는 요약 파일입니다.

최소 조건:

```json
{
  "source": "SCLAS_ABAQUS_ODB_EXTRACTOR",
  "odb_extraction": {
    "status": "extracted",
    "rows_written": 2
  }
}
```

### `odb_extraction_summary.json`

ODB에서 CSV를 제대로 뽑았는지 기록하는 파일입니다.

최소 조건:

```json
{
  "status": "extracted",
  "rows_written": 2
}
```

## 3. 보광이에게 전달할 한 문장

보광이에게는 아래처럼 전달하면 됩니다.

```text
.cae랑 .inp만 말고, Abaqus job completed 된 .odb랑 그 ODB에서 뽑은 result_data.csv, result_summary.json, odb_extraction_summary.json까지 job folder 형태로 줘야 GUI에서 진짜 결과로 연결할 수 있다.
```

## 4. 현재 보광 백엔드에서 확인된 첫 번째 blocking error

검토한 주요 폴더:

```text
C:\HELIX\Abaqus+_work
C:\KYJ
```

현재 작업 본체에 가까운 폴더:

```text
C:\HELIX\Abaqus+_work\for_test
```

확인한 파일:

```text
C:\HELIX\Abaqus+_work\for_test\Cable_Bending.dat
C:\HELIX\Abaqus+_work\for_test\Cable_Bending.inp
C:\HELIX\Abaqus+_work\for_test\result_data.csv
C:\HELIX\Abaqus+_work\for_test\abaqus_mesh_manifest.json
```

첫 번째 blocking error:

```text
***ERROR: DEGREE OF FREEDOM 2 DOES NOT EXIST FOR NODE 1 (ASSEMBLY).
          IT HAS ALREADY BEEN ELIMINATED BY ANOTHER EQUATION, MPC, RIGID BODY,
          KINEMATIC COUPLING CONSTRAINT, TIE CONSTRAINT OR EMBEDDED ELEMENT
          CONSTRAINT. THE REQUIRED EQUATION CANNOT BE FORMED.
```

이어지는 에러:

```text
***ERROR: DEGREE OF FREEDOM 4 DOES NOT EXIST FOR NODE 1 (ASSEMBLY).
***ERROR: 1 nodes are missing degree of freedoms.
```

## 5. blocking error 원인 판단

`Cable_Bending.inp`에서 아래 구조가 확인되었습니다.

```text
*Nset, nset=RP
 1,
*Nset, nset=m_Set-1
 1,
*Nset, nset=m_Set-2
 1,

*Coupling, constraint name=Constraint-1, ref node=m_Set-1, surface=s_Surf-1
*Kinematic
*Coupling, constraint name=Constraint-2, ref node=m_Set-2, surface=s_Surf-2
*Kinematic

*Equation
3
m_Set-1, 2, 1.
m_Set-2, 2, -1.
RP, 1, 27424.8

*Equation
3
m_Set-1, 4, 1.
m_Set-2, 4, -1.
RP, 1, -234.2
```

문제는 `RP`, `m_Set-1`, `m_Set-2`가 모두 assembly node 1을 가리키는 점입니다.

같은 node에 `*Coupling`과 `*Equation`이 동시에 걸리면서 Abaqus가 이미 제거된 DOF 2, DOF 4를 다시 equation에서 사용하려고 하고 있습니다.

쉽게 말하면, 같은 점을 여러 구속조건이 동시에 잡아당겨서 Abaqus가 자유도를 제거한 뒤 다시 그 자유도를 equation에서 쓰려고 해서 preprocessing 단계에서 죽은 상태입니다.

따라서 현재 문제는 해석 수렴 조건 이전의 input deck constraint 정의 오류입니다.

## 6. 보광 쪽 우선 수정 방향

권장 순서:

1. `RP`, `m_Set-1`, `m_Set-2`를 같은 node로 두지 말고 독립 reference point/node로 분리합니다.
2. kinematic coupling으로 제거된 DOF를 `*Equation`에서 다시 쓰지 않게 coupling/equation 조합을 재정리합니다.
3. reduced model에서 먼저 `.dat`의 fatal error가 0개가 되는지 확인합니다.
4. 그 다음 solver convergence, contact, friction, bending step을 다룹니다.
5. ODB가 생성되면 ODB extractor를 통해 `result_data.csv`를 만듭니다.
6. `result_summary.json.source = SCLAS_ABAQUS_ODB_EXTRACTOR`가 되게 정리합니다.

## 7. 현재 `for_test` 결과 상태

`C:\HELIX\Abaqus+_work\for_test\abaqus_mesh_manifest.json` 상태:

```json
{
  "status": "abaqus_inp_created",
  "files": [
    "Cable_Bending.inp",
    "Cable_Bending.cae"
  ],
  "job_name": "Cable_Bending"
}
```

즉 현재 상태는 `.inp/.cae` 생성까지입니다.

`C:\HELIX\Abaqus+_work\for_test\result_data.csv` 상태:

```csv
curvature_1_per_m,moment_kn_m
0,0
```

이 파일은 실제 ODB 추출 결과가 아니라 placeholder입니다.

현재 폴더에는 아래 파일이 없습니다.

```text
result_summary.json
odb_extraction_summary.json
```

따라서 현재 백엔드 산출물은 GUI에 최종 해석 결과로 연결하기에는 아직 부족합니다.

## 8. 내가 백엔드 입장에서 한 일

직접 Abaqus 물리 모델을 완성한 것은 아니지만, GUI와 Abaqus backend가 연결될 수 있는 입출력 계약, 검증 구조, 오류 진단 기준을 만들었습니다.

### 8.1 GUI 입력값을 백엔드 JSON 계약으로 정리

GUI에서 사용자가 입력하는 값을 백엔드가 읽을 수 있는 구조로 정리했습니다.

대상 범위:

```text
geometry_mm
derived_geometry_mm
armour
materials
mesh
analysis_conditions
solver
output_requests
modeling
```

즉 사용자가 GUI에서 바꾸는 아래 값들이 backend JSON으로 넘어갈 수 있게 구조를 잡았습니다.

```text
코어 반지름
아머 개수
재료 물성
밀도
마찰계수
외부 압력
굽힘
메시 분할 개수
filler divisions
```

### 8.2 메시/해석 변수를 GUI에서 조절 가능하게 정리

GUI에서 조절하는 메시 항목을 아래처럼 정리했습니다.

```text
Axial z divisions
Core/Sheath θ divisions
Armour wire θ divisions
Inner sheath r divisions
Bedding r divisions
Outer sheath r divisions
Filler z divisions
```

이 값들은 나중에 보광 백엔드에서 Abaqus mesh seed, partition, sweep division에 연결할 수 있습니다.

### 8.3 GUI preview와 실제 Abaqus backend 역할을 분리

현재 GUI mesh preview는 실제 Abaqus mesh가 아니라 사용자가 설정한 값에 따라 대략적인 메시 밀도와 형상을 보여주는 preview입니다.

역할 분담:

```text
GUI:
입력값 생성, preview, 결과 표시

Abaqus backend:
실제 CAE/INP 생성, solver 실행, ODB 생성, ODB 추출

GUI diagnostics:
결과 파일이 진짜인지 검사
```

### 8.4 Abaqus bridge 건강검진 통과

SmallSmoke를 통해 Abaqus bridge가 최소 동작하는지 확인했습니다.

성공 기준:

```text
Abaqus job completed
ODB extraction status: extracted
result_summary.json.source == SCLAS_ABAQUS_ODB_EXTRACTOR
odb_extraction.rows_written >= 2
```

확인된 결과:

```text
source = SCLAS_ABAQUS_ODB_EXTRACTOR
odb_extraction.status = extracted
rows_written = 25
```

의미:

```text
Abaqus를 실행하고 ODB에서 CSV를 뽑는 최소 bridge 경로가 살아 있음.
```

### 8.5 CurveV0 endpoint sweep 검증

여러 curve factor에 대해 child job을 돌리고 parent `result_data.csv`를 만드는 구조를 확인했습니다.

검증 factor:

```text
-0.1, -0.05, 0, 0.05, 0.1
```

성공 기준:

```text
parent result_data.csv 5 rows
parent source = SCLAS_CURVE_V0_ENDPOINT_SWEEP
endpoint_sweep_validation.all_child_jobs_validated = true
child source = SCLAS_ABAQUS_ODB_EXTRACTOR
child odb_extraction.status = extracted
```

의미:

```text
단일 Abaqus job뿐 아니라 여러 endpoint child job을 돌려 parent 결과로 합치는 sweep 구조도 검증함.
```

### 8.6 결과 파일 검증 기준 정립

보광이가 결과를 주면 아래 기준으로 바로 판단할 수 있게 만들었습니다.

확인 기준:

```text
result_data.csv가 placeholder인지
result_summary.json.source가 맞는지
odb_extraction.status가 extracted인지
rows_written >= 2인지
.dat/.msg/.sta에 ERROR/FATAL이 있는지
child job들이 모두 validated인지
```

### 8.7 보광 백엔드 파일의 첫 blocking error 식별

검토한 폴더:

```text
C:\HELIX\Abaqus+_work
C:\KYJ
```

확인한 첫 blocking error:

```text
C:\HELIX\Abaqus+_work\for_test\Cable_Bending.dat
DEGREE OF FREEDOM 2 DOES NOT EXIST FOR NODE 1
```

원인:

```text
RP, m_Set-1, m_Set-2가 같은 node 1
Coupling과 Equation 충돌
```

이 분석을 통해 단순히 “해석이 안 됨”이 아니라 “어디서 왜 죽는지”를 pinpoint했습니다.

### 8.8 GUI를 발표/시연 가능한 수준으로 정리

백엔드 결과가 오기 전에도 사용자가 입력과 분석 준비 과정을 볼 수 있도록 GUI를 다듬었습니다.

반영 내용:

```text
재료 물성 카테고리화
밀도 단위 ρ (kg/m³)
포아송비 ν
각도 α
메시 방향 θ, r, z
변수 첨자 표시
한국어/영어 토글 정리
글꼴 통일
Material Table 접이식 처리
메시 preview 화면 잘림 개선
불필요한 버튼/배너 정리
HELIX 로고/splash 반영
```

## 9. 보고자료에 쓸 수 있는 문장

아래 문장을 그대로 보고자료에 사용할 수 있습니다.

```text
본인은 GUI-Abaqus 연동을 위한 입력/출력 계약을 정리하고, 사용자가 설정한 기하, 재료, 메시, 해석 조건이 Abaqus backend로 전달될 수 있도록 JSON 기반 bridge 구조를 구축하였다. 또한 SmallSmoke 및 CurveV0 endpoint sweep 검증을 통해 Abaqus job 실행, ODB 추출, result_data.csv 생성, parent-child sweep 결과 통합이 정상 동작함을 확인하였다. 이후 백엔드 담당자가 작성한 Abaqus 모델 파일을 검토하여 현재 해석 실패 원인이 수렴 조건이 아니라 reference node와 coupling/equation 간 자유도 충돌임을 확인하였다. 이에 따라 backend 측에는 실제 ODB 기반 결과 파일과 result_summary/odb_extraction_summary 계약을 만족하는 job folder를 전달받도록 인수인계하였다.
```

짧은 버전:

```text
본인은 Abaqus 물리 모델 자체보다, GUI와 Abaqus backend 사이의 입출력 계약, 결과 검증 체계, sweep 실행 구조, 그리고 백엔드 오류 진단 기준을 구축하였다.
```

## 10. 보광이에게 보낼 메시지

아래 문장을 그대로 전달해도 됩니다.

```text
지금 GUI 쪽은 입력값을 input_data.json 계약으로 넘기고, 결과는 result_data.csv, result_summary.json, odb_extraction_summary.json으로 받는 구조로 맞춰놨어.

확인한 백엔드 첫 에러는 Cable_Bending.dat에서 DEGREE OF FREEDOM 2 DOES NOT EXIST FOR NODE 1이고, RP, m_Set-1, m_Set-2가 같은 node 1을 쓰면서 *Coupling과 *Equation이 충돌하는 게 원인으로 보여.

그래서 .cae/.inp만 말고, Abaqus job completed 된 .odb랑 ODB에서 추출한 result_data.csv, result_summary.json, odb_extraction_summary.json까지 job folder 형태로 주면 GUI에서 바로 결과 표시/진단할 수 있어.
```

## 11. Git에 올리면 안 되는 파일

아래 파일은 대용량이거나 로컬 Abaqus 산출물이므로 Git에 올리지 않습니다.

```text
jobs 폴더 안 대용량 결과물
*.cae
*.odb
*.inp
*.dat
*.msg
*.sta
*.sim
*.prt
*.lck
```

Git에 올려도 되는 파일:

```text
code/*.py
docs/internal_handoff/*.md
assets/fonts/README.md
```

