# Abaqus 백엔드 구현 계획

이 문서는 현재 `code/abaqus_runner.py`를 기준으로, 실제 Abaqus 해석을 어떻게
붙이면 되는지 단계별로 정리한 것입니다.

가장 중요한 GUI와 백엔드의 약속은 아래 CSV 형식입니다.

```csv
curvature_1_per_m,moment_kn_m
```

GUI는 `result_data.csv`의 위 header를 기준으로 bending moment-curvature 곡선을
읽습니다. 실제 Abaqus 해석을 붙이더라도 이 header는 유지해야 합니다.

## 현재 백엔드 상태

현재 `code/abaqus_runner.py`는 두 가지 방식으로 동작합니다.

일반 Python에서 실행할 경우:

- `input_data.json` 읽기
- placeholder `result_data.csv` 생성
- `result_summary.json` 생성
- `abaqus_mesh_manifest.json` 생성

Abaqus/CAE 내부에서 실행할 경우:

- core/sheath solid와 helical armour beam path 생성 시도
- `.cae`, `.inp` mesh scaffold 생성 시도
- 그래도 GUI 확인용 placeholder `result_data.csv`는 생성

즉, 지금은 실제 해석 solve까지 끝난 상태가 아니라, Abaqus 모델 생성을 시작하기 위한
scaffold 단계입니다.

## 1단계: Mesh scaffold 검증

GUI에서 job을 만든 뒤, job 폴더 안에서 아래 명령을 실행합니다.

```bat
abaqus cae noGUI=abaqus_runner.py -- input_data.json
```

그 다음 생성된 파일을 확인합니다.

```text
sclas_mesh_model.cae
<job_name>_mesh.inp
abaqus_mesh_manifest.json
```

확인할 것:

- core 위치와 반지름이 맞는지
- inner armour / outer armour 중심 반지름이 맞는지
- armour wire 개수가 맞는지
- helix 방향과 lay angle이 의도와 맞는지
- GUI Mesh 탭의 axial/circumferential division 값이 반영됐는지

완료 기준:

- `.cae`, `.inp` 파일이 Abaqus에서 에러 없이 열림
- `abaqus_mesh_manifest.json`에 주요 component가 기록됨

## 2단계: Contact-friction 정의

`input_data.json` 안의 아래 항목을 기준으로 contact pair를 정의합니다.

```text
numerical_model.contact_interfaces
```

우선적으로 정의할 contact:

- inner armour ↔ inner sheath
- inner armour ↔ bedding
- outer armour ↔ bedding
- outer armour ↔ outer sheath
- 필요 시 inner/outer armour layer 사이 상호작용

권장 contact 설정:

- normal behavior: penalty 또는 augmented Lagrange
- tangential behavior: regularized Coulomb friction
- friction coefficient:
  `analysis_conditions.friction_coefficient`
- residual contact pressure:
  `analysis_conditions.residual_contact_pressure_mpa`
- contact regularization:
  `analysis_conditions.contact_regularization_beta`

완료 기준:

- contact 정의가 Abaqus 모델에 포함됨
- contact/friction 파라미터가 `result_summary.json`에 기록됨
- 수렴 문제나 failed increment가 있으면 `result_summary.json`에 기록됨

## 3단계: Cyclic bending 해석 추가

GUI에서 전달되는 주요 입력:

```text
analysis_conditions.max_curvature_1_per_m
analysis_conditions.loading_cycles
analysis_conditions.effective_length_mm
analysis_conditions.solver_steps
```

해야 할 일:

1. 주어진 최대 곡률과 cycle 수를 이용해 cyclic curvature path 정의
2. cable 양 끝에 회전/변위 boundary condition 적용
3. Abaqus job submit
4. ODB에서 reaction moment와 curvature history 추출
5. `result_data.csv`에 저장

완료 기준:

- `result_data.csv`가 placeholder가 아니라 ODB 추출값으로 채워짐
- GUI에서 moment-curvature hysteresis loop가 표시됨
- `result_summary.json.source`가 실제 Abaqus solve임을 나타냄

## 4단계: ODB 후처리

ODB에서 추출하면 좋은 값:

- peak absolute bending moment
- min/max moment
- hysteresis loop energy
- contact pressure range
- slip displacement range
- stick/slip transition 관련 지표
- failed increment 또는 convergence warning

주의:

- `result_data.csv`는 계속 moment-curvature curve 전용으로 유지
- 부가 지표는 `result_summary.json`에 저장

## 5단계: Coupled study 추가

bending 해석이 안정화된 뒤 추가하면 되는 항목입니다.

### Torsion stiffness

입력:

```text
analysis_conditions.max_twist_rad_per_m
```

출력:

```text
result_summary.json
```

에 torsional stiffness 저장.

### Tension-bending coupling

입력:

```text
analysis_conditions.max_axial_strain
```

방법:

- axial preload 적용
- 그 상태에서 cyclic bending 수행
- axial force / bending moment 변화 확인

### Pressure / compression / bird-caging

입력:

```text
analysis_conditions.hydrostatic_pressure_mpa
analysis_conditions.radial_compression_ratio
```

출력:

- pressure softening factor
- radial deformation
- bird-caging risk index

## 6단계: GUI 확장 기준

새로운 결과 plot은 백엔드 결과가 안정적으로 나온 뒤에 추가합니다.

추가 후보:

- contact pressure vs curvature
- slip displacement vs curvature
- torsion moment vs twist
- axial force vs axial strain
- pressure sweep summary

단, 모든 결과를 `result_data.csv`에 넣지는 않습니다.
`result_data.csv`는 bending moment-curvature 곡선 전용으로 유지하고,
추가 결과는 별도 CSV 또는 `result_summary.json`에 넣는 방식이 좋습니다.

## 가장 먼저 할 일 요약

1. GUI로 job package 생성
2. job 폴더에서 Abaqus command 실행
3. `.cae`, `.inp` scaffold 열어서 geometry 확인
4. contact pair 정의
5. cyclic bending boundary condition 추가
6. ODB에서 moment-curvature 추출
7. `result_data.csv` 생성
