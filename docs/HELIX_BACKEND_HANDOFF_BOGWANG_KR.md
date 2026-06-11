# HELIX Abaqus 백엔드 전달 문서

대상: 보광이  
목적: HELIX GUI가 생성하는 job package를 Abaqus 백엔드에서 받아 실제 해석 결과로 되돌려주는 작업을 시작하기 위한 계약/체크리스트입니다.

HELIX는 **Helical Element Localised Interaction eXamination**의 약자입니다. GUI는 사용자가 해저 케이블 형상, 재료, 메시 요청, 해석 조건을 입력하는 프론트엔드이고, Abaqus 백엔드는 같은 job 폴더 안에서 실제 유한요소 모델 생성, 접촉 정의, 해석, ODB 후처리를 담당합니다.

## 먼저 받을 파일

GitHub 저장소 전체를 받는 것이 가장 안전합니다.

```bat
git clone https://github.com/jhpark391-afk/SCLAS-cable-analysis.git
cd SCLAS-cable-analysis
```

이미 받은 저장소라면:

```bat
git pull
```

백엔드 작업에 직접 필요한 핵심 파일은 아래입니다.

```text
code/abaqus_runner.py
code/sclas_remote_gui.py
run_sclas.bat
run_self_check.bat
setup_windows.bat
README_BOGWANG_HANDOFF_KR.md
docs/HELIX_BACKEND_HANDOFF_BOGWANG_KR.md
docs/ABAQUS_BACKEND_IMPLEMENTATION_PLAN_KR.md
screenshots/gui/helix_gui_01_design.png
screenshots/gui/helix_gui_02_mesh.png
screenshots/gui/helix_gui_03_analysis.png
screenshots/gui/helix_gui_screenshots.zip
assets/helix_logo.png
```

주의: `data/input_data.json`은 예전 호환용 샘플입니다. 실제 GUI job의 최신 입력 구조는 GUI에서 만든 job 폴더의 `input_data.json`을 기준으로 봐야 합니다.

## 실행 순서

Windows에서 처음 받았을 때:

```bat
setup_windows.bat
run_self_check.bat
run_sclas.bat
```

GUI에서 백엔드용 job package를 만들 때:

1. GUI 실행
2. `Analysis` 탭으로 이동
3. Backend Mode에서 `Export job package only` 선택
4. `Run / Create Job` 클릭
5. 생성된 job 폴더를 Abaqus 작업 폴더로 사용

기본 job 폴더 위치:

```text
jobs/SCLAS_jobs/job_YYYYMMDD_HHMMSS_xxxxxxxx/
```

## Job 폴더 입력 파일

GUI가 job 폴더에 만들어주는 파일:

```text
input_data.json
units_manifest.json
BACKEND_CONTRACT.md
abaqus_runner.py
```

백엔드에서 우선 읽어야 하는 파일은 `input_data.json`입니다.

주요 입력 구조:

```text
metadata
units
geometry_mm
derived_geometry_mm
armour
materials
mesh
analysis_conditions
study_scope
numerical_model
equivalent_properties
backend_output_contract
```

백엔드에서 특히 중요한 key:

```text
derived_geometry_mm.outer_sheath_outer_radius_mm
derived_geometry_mm.inner_armour_center_radius_mm
derived_geometry_mm.outer_armour_center_radius_mm
armour.inner_wire_count
armour.outer_wire_count
armour.inner_lay_angle_deg
armour.outer_lay_angle_deg
materials
mesh.requested_element_type
mesh.model_strategy
mesh.armour_model
mesh.axial_divisions
mesh.core_circumferential_divisions
mesh.armour_circumferential_divisions
analysis_conditions.effective_length_mm
analysis_conditions.max_curvature_1_per_m
analysis_conditions.loading_cycles
analysis_conditions.solver_steps
analysis_conditions.friction_coefficient
analysis_conditions.residual_contact_pressure_mpa
analysis_conditions.contact_regularization_beta
numerical_model.contact_interfaces
numerical_model.contact_interface_defaults
```

## Abaqus 실행 명령

job 폴더 안에서 실행:

```bat
abaqus cae noGUI=abaqus_runner.py -- input_data.json
```

현재 `code/abaqus_runner.py`는 두 단계 상태입니다.

- 일반 Python 실행: placeholder 결과 CSV/JSON 생성
- Abaqus/CAE 실행: CAE/INP mesh scaffold 생성 시도 후 placeholder 결과 생성

즉, 지금 할 일은 placeholder curve를 실제 Abaqus solve 및 ODB 추출 결과로 교체하는 것입니다.

## 백엔드가 반드시 만들어야 하는 출력

필수:

```text
result_data.csv
```

CSV header는 반드시 아래 그대로 유지해야 합니다.

```csv
curvature_1_per_m,moment_kn_m
```

GUI는 이 두 column 이름으로 moment-curvature 그래프를 읽습니다. header가 바뀌면 GUI가 결과를 못 읽습니다.

선택이지만 강력 권장:

```text
result_summary.json
abaqus_mesh_manifest.json
sclas_mesh_model.cae
<job_name>_mesh.inp
```

## result_summary.json 권장 구조

최소 권장 예시:

```json
{
    "source": "ABAQUS_BACKEND",
    "status": "completed",
    "computed_at": "2026-06-11T19:00:00",
    "max_abs_moment_kn_m": 0.0,
    "min_moment_kn_m": 0.0,
    "max_moment_kn_m": 0.0,
    "hysteresis_loss_kj_per_m_proxy": 0.0,
    "num_points": 500,
    "mesh_status": {
        "status": "abaqus_mesh_created",
        "manifest": "abaqus_mesh_manifest.json"
    },
    "contact_friction": {
        "friction_coefficient": 0.22,
        "residual_contact_pressure_mpa": 0.30,
        "regularization_beta": 0.001,
        "convergence_status": "ok"
    },
    "backend_readiness": {
        "bending_stick_slip": {
            "requested": true,
            "status": "odb_extracted"
        },
        "contact_friction": {
            "requested": true,
            "status": "defined"
        },
        "torsion": {
            "requested": false,
            "status": "not_run"
        },
        "tension_bending_coupling": {
            "requested": false,
            "status": "not_run"
        },
        "compression_bird_caging": {
            "requested": false,
            "status": "not_run"
        },
        "pressure_effect": {
            "requested": true,
            "status": "included"
        }
    },
    "note": "Real Abaqus ODB result."
}
```

추가 지표는 `result_summary.json`에 계속 확장하면 됩니다. 단, `result_data.csv`는 bending moment-curvature 곡선 전용으로 유지합니다.

## 구현 우선순위

1. **Mesh scaffold 검증**
   - `.cae`, `.inp`가 Abaqus에서 열리는지 확인
   - core 위치, sheath radius, armour radius, wire count 확인
   - lay angle 방향 확인

2. **Contact/friction 정의**
   - `numerical_model.contact_interfaces` 기준
   - inner armour to inner sheath
   - inner armour to bedding
   - outer armour to bedding
   - outer armour to outer sheath
   - 필요 시 inner/outer armour layer interaction

3. **Cyclic bending boundary condition**
   - `max_curvature_1_per_m`
   - `loading_cycles`
   - `effective_length_mm`
   - `solver_steps`
   - 위 값으로 curvature path 생성

4. **Abaqus solve 실행**
   - convergence warning, failed increment 기록
   - 수렴 실패 시에도 `result_summary.json.status`에 실패 사유 기록

5. **ODB 후처리**
   - curvature history
   - reaction moment history
   - `result_data.csv` 생성
   - peak moment, loop loss, contact/slip 지표를 `result_summary.json`에 저장

6. **추가 연구 항목**
   - torsion stiffness
   - tension-bending coupling
   - hydrostatic pressure softening
   - compression/bird-caging risk

## GUI에서 기대하는 결과 확인

결과 파일이 생성되면 GUI의 `Analysis` 탭에서:

- `Load result CSV`로 `result_data.csv` 수동 로드 가능
- `Compare CSV`로 FAST preview와 Abaqus 결과 비교 가능
- `result_summary.json`이 같은 폴더에 있으면 요약 패널에 자동 반영

참고용 GUI 캡처:

```text
screenshots/gui/helix_gui_01_design.png
screenshots/gui/helix_gui_02_mesh.png
screenshots/gui/helix_gui_03_analysis.png
screenshots/gui/helix_gui_screenshots.zip
```

## 완료 기준

1차 완료:

- Abaqus에서 `.cae`/`.inp` scaffold 확인 완료
- 실제 접촉 pair가 모델에 포함됨
- 실제 cyclic bending job이 submit됨
- ODB에서 추출한 `result_data.csv`가 GUI에서 표시됨
- `result_summary.json.source`가 `ABAQUS_BACKEND`로 기록됨

2차 완료:

- stick-slip/hysteresis loop가 FAST preview와 비교 가능
- friction/residual pressure sensitivity를 최소 2~3개 case로 비교 가능
- contact pressure 또는 slip displacement 지표가 `result_summary.json`에 기록됨

## 주의할 점

- 단위는 대부분 mm, MPa, degree, 1/m입니다. `units`와 `units_manifest.json`을 반드시 확인하세요.
- `moment_kn_m`은 kN.m 단위입니다.
- GUI의 FAST 결과는 프리뷰일 뿐이고 최종 해석값이 아닙니다.
- `mesh.model_strategy = periodic_homogenized_cell`이면 전체 길이 모델보다 주기 셀 접근이 우선입니다.
- GUI 콤보박스 문구는 영어로 유지됩니다. 화면 언어 토글은 UI 표시용이고 JSON 계약값은 깨지지 않게 유지합니다.
