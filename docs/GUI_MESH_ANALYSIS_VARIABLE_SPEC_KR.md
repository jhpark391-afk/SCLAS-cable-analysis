# 2026-07-09 Current GUI-Backend Variable Baseline

이 문서의 이전 표 일부는 2026-06-26 초안 기준이다. 2026-07-09 현재 구현 기준은 아래를 우선한다.

| 항목 | 현재 구현 기준 |
|---|---|
| Core count | `geometry_mm.core_count`, 기본값 `3`, 현재 backend 기본 3-core 모델과 정렬 |
| Pitch angle input | 사용자는 `armour.core_lay_angle_deg`, `armour.inner_armour_lay_angle_deg`, `armour.outer_armour_lay_angle_deg`를 입력 |
| Pitch length derived values | GUI가 `derived_geometry_mm.*_pitch_length_mm`와 `armour.*_pitch_mm`를 생성 |
| Effective length | `analysis_conditions.effective_length_mm = derived_geometry_mm.core_pitch_length_mm / geometry_mm.core_count`; GUI에서는 읽기 전용 표시값 |
| Axial z division | `mesh.axial_divisions` 하나가 core/sheath/bedding/armour/filler 전체에 적용 |
| Filler z division | 별도 GUI 입력 없음. `mesh.filler_z_divisions`는 backward compatibility mirror이며 `mesh.filler_z_divisions_source = same_as_axial_divisions` |
| Exchange contract | `input_data.json.backend_exchange_contract`와 `docs/guides/SCLAS_GUI_BACKEND_EXCHANGE_CONTRACT_KR.md`를 우선 참조 |

---
# SCLAS Mesh / Analysis GUI-Abaqus Variable Contract

작성 상태: Draft v0.1  
작성 목적: 2026-06-26 ABAQUS Mesh 및 해석 조건 설정 회의 내용을 GUI와 Abaqus 자동화 코드 사이의 변수 계약으로 정리한다.  
작성 기준: 현재 GitHub `main` 구조와 회의 공지/영상 화면 기반 1차 정리. 음성 전사본이 없으므로 Abaqus 세부 수치와 옵션명은 보광/현수 검토 후 확정한다.  
2026-07-02 추가 반영: `메시-분석_변수.docx`의 R/Theta/Z mesh 변수표와 analysis 변수 메모를 반영했다.

## 1. 목적

이 문서는 SCLAS GUI의 Mesh 탭과 Analysis 탭에서 어떤 변수를 입력받고, 그 변수를 `input_data.json`에 어떤 key로 저장하며, Abaqus 자동화 스크립트가 어떤 의미로 해석해야 하는지 정의하는 초안이다.

핵심 목표는 다음과 같다.

- 지호: Mesh/Analysis GUI 탭과 GUI 내부 mesh preview 구현
- 보광: GUI가 넘긴 변수 기반 Abaqus mesh/analysis 자동화 스크립트 구현
- 현수: 실제 굽힘 해석을 수행하며 수렴 조건, 접촉 조건, 모델링 수정 요구사항 피드백

이 문서는 최종 해석 조건 문서가 아니라, 세 사람 사이의 GUI-Abaqus 변수 계약 초안이다.

## 2. 역할 분담

| 담당 | 역할 | 이 문서에서 확인할 부분 |
|---|---|---|
| 지호 | GUI 입력 항목, layout, preview, `input_data.json` export | GUI label, control type, JSON key, default |
| 보광 | Abaqus mesh/analysis 자동화 구현 | Abaqus meaning, supported values, required/optional |
| 현수 | 실제 해석 수행, 수렴성 조건 도출, 모델링 피드백 | convergence controls, contact options, output requests |

권장 workflow:

```text
지호가 변수 계약 초안 작성
-> 보광이 Abaqus 구현 가능 여부와 변수명 검토
-> 현수가 실제 해석 중 필요한 조건/범위 피드백
-> GUI와 Abaqus runner를 같은 JSON 계약으로 수정
```

## 3. 모델 선택

회의 이후 목표에는 Full 3D 모델 외에 두 종류의 등가 모델이 포함된다. GUI 두 번째 탭 또는 Mesh 탭 상단에서 사용자가 모델 종류를 선택해야 한다.

| GUI Label | JSON key | JSON value | Abaqus 의미 | 상태 |
|---|---|---|---|---|
| Full 3D model | `modeling.model_type` | `full_3d` | 현재 Abaqus 파일 기준 전체 3D 케이블 모델 | 우선 구현 |
| Armour equivalent model | `modeling.model_type` | `armour_equivalent` | armour layer를 등가 물성/등가 단면으로 치환한 모델 2 | 보광 검토 필요 |
| Armour + Core equivalent model | `modeling.model_type` | `armour_core_equivalent` | armour와 core 영역까지 등가화한 모델 3 | 보광 검토 필요 |

보조 key:

| JSON key | Type | Default | 의미 |
|---|---|---:|---|
| `modeling.model_label` | string | `Full 3D` | GUI 표시용 이름 |
| `modeling.equivalent_model_level` | int | `1` | 1=Full 3D, 2=Armour equivalent, 3=Armour+Core equivalent |
| `modeling.use_equivalent_properties` | bool | `false` | 등가 물성 사용 여부 |

## 4. 회의 문서 반영 사항

`메시-분석_변수.docx`의 핵심 요구사항은 다음과 같다.

- 기하 모델링은 `x/y/z` 좌표계 기준이지만, 단면이 `x/y` 평면이므로 사용자는 mesh 설정을 원통 좌표계 `R/Theta/Z` 기준으로 이해하는 편이 좋다.
- GUI에서 사용자가 "어디 mesh를 설정 중인지" 눈으로 확인할 수 있어야 한다.
- 예: Core의 Z축 mesh를 설정 중이면 core의 길이방향 선분이 preview에서 강조된다.
- Mesh 입력 방식은 component와 axis에 따라 다르다.
  - `X`: 사용하지 않는 항목
  - `개수`: 분할 개수 기반 mesh 설정
  - `사이즈`: 길이 기반 mesh 설정, 예: 6 mm
  - `사이즈/개수 선택 가능`: 사용자가 size 방식과 count 방식을 선택
- `Fillter`는 형상이 특이하므로 별도 그림/preview 처리가 필요하다. 실제 명칭은 `Filler`인지 `Fillter`인지 보광/현수 확인이 필요하다.
- Filler/Fillter는 오른쪽 참고 그림처럼 4파트로 나누어 size/count를 자유롭게 선택할 수 있으면 좋다.

### 4.1 Component별 R/Theta/Z mesh control

| Component | R axis | Theta axis | Z axis | GUI 구현 메모 |
|---|---|---|---|---|
| Core | 사용 안 함 | 개수 | 사이즈/개수 선택 가능 | 3-core 각각 또는 공통 설정 여부 확인 |
| Bedding | 사용 안 함 | 개수 | 사이즈/개수 선택 가능 | annular layer |
| InnerSheath | 개수 선택: 1, 3, 5 | 개수 | 사이즈/개수 선택 가능 | radial partition selector 필요 |
| OuterSheath | 개수 선택: 1, 3, 5 | 개수 | 사이즈/개수 선택 가능 | 문서 원문 `OutherSheath`; GUI 표기는 `OuterSheath` 권장 |
| InnerArmour | 사용 안 함 | 개수 | 사이즈/개수 선택 가능 | beam/solid/equivalent 표현에 따라 의미 변경 |
| OuterArmour | 사용 안 함 | 개수 | 사이즈/개수 선택 가능 | beam/solid/equivalent 표현에 따라 의미 변경 |
| Fillter/Filler | 별도 처리 | 별도 처리 | 사이즈/개수 선택 가능 | 4-part special geometry preview 필요 |

권장 JSON 구조:

```json
{
  "mesh_controls": {
    "coordinate_basis": "cylindrical_r_theta_z",
    "components": {
      "Core": {
        "r": {"mode": "disabled"},
        "theta": {"mode": "count", "count": 24},
        "z": {"mode": "count", "count": 40, "size_mm": null}
      },
      "InnerSheath": {
        "r": {"mode": "count_choice", "allowed_counts": [1, 3, 5], "count": 1},
        "theta": {"mode": "count", "count": 24},
        "z": {"mode": "count", "count": 40, "size_mm": null}
      }
    }
  }
}
```

GUI 구현상으로는 모든 component에 같은 widget을 쓰되, axis별 `mode`를 보고 disabled/count/size/count-or-size control을 바꾸는 구조가 좋다.

## 5. Mesh 탭 변수

### 5.1 Model Strategy

| GUI Label | Control | JSON key | Type | Default | Abaqus meaning | 담당 |
|---|---|---|---|---:|---|---|
| Model type | segmented control | `modeling.model_type` | enum | `full_3d` | 생성할 Abaqus 모델 family | 지호/보광 |
| Mesh strategy | combo | `mesh.model_strategy` | enum | `periodic_homogenized_cell` | 전체 모델 또는 주기/등가 cell 전략 | 보광 |
| Armour representation | combo | `mesh.armour_model` | enum | `beam_with_contact_surface` | armour를 beam, solid, equivalent 중 무엇으로 표현할지 | 보광 |
| Use reduced smoke mesh | checkbox | `mesh.lab_smoke_reduced_mesh` | bool | `false` | 연구실 검증용 축소 mesh | 현수/보광 |

권장 enum:

```text
mesh.model_strategy:
- full_length_3d
- periodic_homogenized_cell
- reduced_validation_cell

mesh.armour_model:
- solid_wire
- beam_with_contact_surface
- equivalent_layer
```

### 5.2 Mesh Density

| GUI Label | Control | JSON key | Type | Default | Unit | Abaqus meaning | 검토 필요 |
|---|---|---|---|---:|---|---|---|
| Global seed size | numeric input | `mesh.global_seed_size_mm` | float | `2.0` | mm | Abaqus seed part/global size | 보광 |
| Axial divisions | stepper | `mesh.axial_divisions` | int | `40` | count | 길이 방향 분할 수 | 현수 |
| Core circumferential divisions | stepper | `mesh.core_circumferential_divisions` | int | `24` | count | core/solid layer 원주 분할 | 현수 |
| Armour circumferential divisions | stepper | `mesh.armour_circumferential_divisions` | int | `8` | count | armour wire 또는 등가 layer 원주 분할 | 현수 |
| Radial divisions per layer | stepper | `mesh.radial_divisions_per_layer` | int | `1` | count | sheath/bedding 등 radial partition 수 | 보광 |
| Local refinement factor | slider | `mesh.local_refinement_factor` | float | `1.0` | ratio | 접촉부 국부 mesh refinement | 현수/보광 |
| Effective model length | numeric input | `analysis_conditions.effective_length_mm` | float | `50.0` | mm | 축소 cell 또는 bending validation 길이 | 현수 |

주의:

- `global_seed_size_mm`와 `axial_divisions`가 동시에 존재할 때 Abaqus runner에서 어느 값이 우선인지 정해야 한다.
- 축소 smoke/검증 모델에서는 `axial_divisions`, `core_circumferential_divisions`, `armour_circumferential_divisions`를 우선 사용한다.

### 5.3 Element and Section

| GUI Label | Control | JSON key | Type | Default | Abaqus meaning |
|---|---|---|---|---:|---|
| Solid element type | combo | `mesh.solid_element_type` | enum | `C3D8` | sheath/bedding/core 등 solid part element |
| Armour element type | combo | `mesh.armour_element_type` | enum | `B31` | armour beam 표현 시 element |
| Equivalent layer element type | combo | `mesh.equivalent_element_type` | enum | `C3D8` | 등가 layer 모델 element |
| Use reduced integration | checkbox | `mesh.use_reduced_integration` | bool | `false` | `R` suffix는 reduced integration이므로 기본 GUI 계약에서는 사용하지 않음 |
| Mesh quality check | checkbox | `mesh.enable_mesh_quality_check` | bool | `true` | mesh 생성 후 quality summary 기록 |

보광 검토 질문:

- Full 3D 모델에서 armour를 solid wire로 구현할 때 사용할 element type은 무엇인가?
- Beam armour와 solid layer contact를 위한 surface/edge set naming convention을 확정해야 하는가?
- Abaqus 2019 기준으로 GUI에서 노출하면 안 되는 element option이 있는가?

## 6. Analysis 탭 변수

### 6.1 Run Mode

| GUI Label | Control | JSON key | Type | Default | 의미 |
|---|---|---|---|---:|---|
| Run mode | segmented control | `analysis_conditions.run_mode` | enum | `fast_preview` | 해석 실행 방식 |
| Save Abaqus files | checkbox | `analysis_conditions.save_abaqus_files` | bool | `true` | `.cae`, `.inp`, manifest 보존 |
| Run solver after mesh | checkbox | `analysis_conditions.run_solver` | bool | `false` | GUI에서 Abaqus solver까지 실행 |
| Extract ODB after solve | checkbox | `analysis_conditions.extract_odb` | bool | `true` | solver 완료 후 ODB 추출 |

권장 enum:

```text
analysis_conditions.run_mode:
- fast_preview
- export_job_only
- small_smoke
- curve_v0_endpoint_sweep
- curve_v0_continuous
- full_solve
```

### 6.2 Bending Setup

| GUI Label | Control | JSON key | Type | Default | Unit | 의미 |
|---|---|---|---|---:|---|---|
| Max curvature | numeric input | `analysis_conditions.max_curvature_1_per_m` | float | `0.08` | 1/m | 목표 최대 곡률 |
| Curvature unit display | combo/label | `analysis_conditions.curvature_unit` | enum | `1_per_m` | - | GUI 표시 단위와 Abaqus 내부 단위 변환 기준 |
| Effective length | numeric input | `analysis_conditions.effective_length_mm` | float | `50.0` | mm | rotation 산정 길이 |
| Curve factors | text/list input | `analysis_conditions.curve_factors` | float list | `[-0.1,-0.05,0,0.05,0.1]` | ratio | endpoint sweep 하중점 |
| Output intervals | stepper | `analysis_conditions.abaqus_output_intervals` | int | `4` | count | ODB frame/output interval |
| Continuous path enabled | checkbox | `analysis_conditions.abaqus_curve_v0` | bool | `false` | 단일 job multi-point curve |
| Endpoint sweep enabled | checkbox | `analysis_conditions.abaqus_curve_v0_endpoint` | bool | `false` | 여러 endpoint job sweep |

계산식:

```text
target_rotation_rad = max_curvature_1_per_m * curve_factor * effective_length_mm / 1000
```

회의 문서 메모:

- 곡률 설정은 Abaqus 모델 단위가 mm 기준이므로 단위 통일이 필요하다.
- GUI는 사람이 이해하기 쉬운 `1/m`를 기본 표시 단위로 유지하되, Abaqus runner 내부에서 `1/mm` 또는 rotation으로 변환하는 방식을 권장한다.
- GUI label에는 `1/m`, `1/mm`, `rad`가 섞이지 않도록 단위 suffix를 항상 표시한다.

### 6.3 Contact and Friction

| GUI Label | Control | JSON key | Type | Default | Unit | 의미 | 상태 |
|---|---|---|---|---:|---|---|---|
| Cable external pressure | numeric input | `analysis_conditions.external_pressure_mpa` | float | `0.0` | MPa | 케이블에 가해지는 외압, Abaqus 기준 MPa | 현수/보광 |
| Friction coefficient | numeric input | `analysis_conditions.friction_coefficient` | float | `0.22` | - | Coulomb friction coefficient | 구현됨/검토 |
| Residual contact pressure | numeric input | `analysis_conditions.residual_contact_pressure_mpa` | float | `0.3` | MPa | 초기/잔류 접촉압 목표 | 물리 구현 미완 |
| Contact regularization beta | numeric input | `analysis_conditions.contact_regularization_beta` | float | `0.001` | - | regularized Coulomb beta | 구현됨/검토 |
| Normal contact formulation | combo | `analysis_conditions.normal_contact` | enum | `penalty_or_augmented_lagrange` | - | normal behavior | 보광 |
| Tangential contact formulation | combo | `analysis_conditions.tangential_contact` | enum | `regularized_coulomb` | - | tangential behavior | 보광 |
| Contact closure overclosure | numeric input | `analysis_conditions.contact_closure_overclosure_mm` | float | `0.0` | mm | 축소 검증용 geometry closure | 실험적 |
| Contact stabilization | checkbox | `analysis_conditions.contact_stabilization_enabled` | bool | `false` | - | convergence stabilization | 현수 |

현재 연구 blocker:

- ODB local field output은 존재하지만 reduced scaffold에서 `CPRESS=0`, slip=0으로 기록되는 상태가 있었다.
- 따라서 residual pressure/preload는 GUI에서 변수로 제공하되, 연구급 완료로 표시하면 안 된다.
- 우선 목표는 SmallSmoke에서 nonzero `CPRESS`가 나오는 contact closure/preload 표현을 확보하는 것이다.
- 회의 문서 기준으로 접촉별 friction coefficient는 우선 모두 같은 값을 입력하는 방식으로 시작한다.

### 6.4 Solver Controls

| GUI Label | Control | JSON key | Type | Default | Unit | 의미 |
|---|---|---|---|---:|---|---|
| Step time | numeric input | `solver.step_time` | float | `1.0` | - | Abaqus StaticStep timePeriod |
| Max calculation time | numeric input | `solver.max_wall_time_min` | float/null | `null` | min | 해석 최대 대기/계산 시간 |
| Initial increment | numeric input | `solver.initial_increment` | float/null | `null` | - | Abaqus initialInc |
| Minimum increment | numeric input | `solver.minimum_increment` | float/null | `null` | - | Abaqus minInc |
| Maximum increment | numeric input | `solver.maximum_increment` | float/null | `null` | - | Abaqus maxInc |
| Maximum increments | stepper | `solver.max_num_increments` | int | `100` | count | Abaqus nlgeom/static increment cap |
| NLGEOM | checkbox | `solver.nlgeom` | bool | `true` | - | geometric nonlinearity |
| Stabilization | checkbox | `solver.stabilization_enabled` | bool | `false` | - | automatic stabilization |
| Stabilization factor | numeric input | `solver.stabilization_factor` | float/null | `null` | - | damping/stabilization factor |

현수 검토 질문:

- 수렴성 판단 기준을 무엇으로 둘 것인가? 예: complete/fail, warning count, negative eigenvalue, cutback 횟수, wall time.
- Full 3D 기준으로 허용 가능한 최대 해석 시간은 얼마인가?
- GUI에서 solver control을 전문가 모드로 숨길지, 기본 탭에 노출할지 결정 필요.
- 회의 문서의 "Step 시간 간격 상한"은 Abaqus `maxInc` 또는 output interval 중 어느 쪽에 대응하는지 보광 확인이 필요하다.

### 6.5 Output Requests

| GUI Label | Control | JSON key | Type | Default | 의미 |
|---|---|---|---|---|---|
| Reference point history | checkbox group | `output_requests.history` | string list | `["UR2","RM2"]` | moment-curvature 추출 |
| Displacement/rotation field | checkbox | `output_requests.field.U_UR` | bool | `true` | `U`, `UR` field output |
| Reaction force/moment field | checkbox | `output_requests.field.RF_RM` | bool | `true` | `RF`, `RM` field output |
| Stress field | checkbox | `output_requests.field.S` | bool | `true` | stress/Mises output |
| Contact pressure | checkbox | `output_requests.field.CPRESS` | bool | `true` | contact pressure |
| Contact opening | checkbox | `output_requests.field.COPEN` | bool | `true` | contact opening/gap |
| Contact slip | checkbox | `output_requests.field.CSLIP` | bool | `true` | `CSLIP1`, `CSLIP2` |
| Contact shear | checkbox | `output_requests.field.CSHEAR` | bool | `true` | `CSHEAR1`, `CSHEAR2` |
| Contact status | checkbox | `output_requests.field.CSTATUS` | bool | `false` | contact status, Abaqus 지원 확인 필요 |

기본 output list:

```json
{
  "history": ["UR2", "RM2"],
  "field": ["U", "UR", "RF", "RM", "S", "CPRESS", "COPEN", "CSLIP1", "CSLIP2", "CSHEAR1", "CSHEAR2"]
}
```

## 7. 제안 `input_data.json` 구조

GUI는 기존 job package 계약을 유지하면서 아래 구조를 추가/정리한다.

```json
{
  "modeling": {
    "model_type": "full_3d",
    "model_label": "Full 3D",
    "equivalent_model_level": 1,
    "use_equivalent_properties": false
  },
  "mesh": {
    "model_strategy": "periodic_homogenized_cell",
    "armour_model": "beam_with_contact_surface",
    "global_seed_size_mm": 2.0,
    "axial_divisions": 40,
    "core_circumferential_divisions": 24,
    "armour_circumferential_divisions": 8,
    "radial_divisions_per_layer": 1,
    "local_refinement_factor": 1.0,
    "solid_element_type": "C3D8",
    "armour_element_type": "B31",
    "equivalent_element_type": "C3D8",
    "use_reduced_integration": true,
    "enable_mesh_quality_check": true
  },
  "analysis_conditions": {
    "run_mode": "curve_v0_endpoint_sweep",
    "max_curvature_1_per_m": 0.08,
    "curvature_unit": "1_per_m",
    "effective_length_mm": 50.0,
    "curve_factors": [-0.1, -0.05, 0.0, 0.05, 0.1],
    "abaqus_output_intervals": 4,
    "external_pressure_mpa": 0.0,
    "friction_coefficient": 0.22,
    "residual_contact_pressure_mpa": 0.3,
    "contact_regularization_beta": 0.001,
    "normal_contact": "penalty_or_augmented_lagrange",
    "tangential_contact": "regularized_coulomb",
    "contact_closure_overclosure_mm": 0.0,
    "contact_stabilization_enabled": false
  },
  "solver": {
    "step_time": 1.0,
    "max_wall_time_min": null,
    "initial_increment": null,
    "minimum_increment": null,
    "maximum_increment": null,
    "max_num_increments": 100,
    "nlgeom": true,
    "stabilization_enabled": false,
    "stabilization_factor": null
  },
  "output_requests": {
    "history": ["UR2", "RM2"],
    "field": ["U", "UR", "RF", "RM", "S", "CPRESS", "COPEN", "CSLIP1", "CSLIP2", "CSHEAR1", "CSHEAR2"]
  }
}
```

## 8. GUI Preview 요구사항

Mesh 탭에는 사용자가 선택한 모델 종류를 직관적으로 볼 수 있는 lightweight preview를 둔다.

| Model type | Preview 요구사항 |
|---|---|
| Full 3D | 3-core 단면, sheath/bedding/outer sheath, inner/outer armour wire ring 표시 |
| Armour equivalent | armour wire ring을 등가 annular layer로 단순화해서 표시 |
| Armour + Core equivalent | core cluster와 armour를 등가 영역으로 단순화해서 표시 |

Preview는 Abaqus mesh를 실제로 생성하는 기능이 아니라, 사용자가 선택한 model abstraction을 이해하는 GUI 그림이다. 실제 Abaqus mesh 검증은 `.cae`, `.inp`, `abaqus_mesh_manifest.json` 기준으로 수행한다.

## 9. 보광에게 확인할 질문

1. `modeling.model_type` enum 이름을 위 제안대로 사용해도 되는가?
2. Full 3D, armour equivalent, armour+core equivalent 각각에서 필요한 mesh 변수는 같은가, 아니면 model별 추가 key가 필요한가?
3. `global_seed_size_mm`와 `axial_divisions` 중 Abaqus runner에서 우선해야 하는 값은 무엇인가?
4. Full 3D armour를 solid wire로 구현할 계획인지, B31 beam + contact surface로 유지할 계획인지?
5. Abaqus 2019에서 안정적으로 지원되는 contact formulation enum은 무엇인가?
6. Residual contact pressure/preload는 어떤 방식으로 구현할 예정인가?
7. GUI가 output request를 checkbox로 세분화해도 되는가, 아니면 backend에서 고정 list로 유지하는 편이 좋은가?
8. 모델 2/3의 등가 물성은 GUI에서 입력받을지, backend 내부 계산/파일로 처리할지?

## 10. 현수에게 확인할 질문

1. 굽힘 해석 수렴성 판단 기준은 무엇인가?
2. SmallSmoke, CurveV0, Full solve 각각의 허용 wall time은 어느 정도인가?
3. friction coefficient, residual contact pressure, external pressure의 parametric study 범위는?
4. Full 3D / 모델 2 / 모델 3 비교 시 동일하게 맞춰야 할 조건은 무엇인가?
5. 히스테리시스 루프 비교 외에 반드시 보고해야 할 지표는 무엇인가?
6. 해석 실패 시 GUI에 표시해야 하는 핵심 메시지는 무엇인가? 예: contact issue, element distortion, too many attempts, overconstraint.

## 11. 지호 구현 순서

1. 이 문서를 보광/현수에게 전달하고 변수명/default 검토를 받는다.
2. `code/sclas_remote_gui.py`에서 현재 Mesh/Analysis 탭이 이미 export하는 key를 확인한다.
3. 기존 key와 충돌하지 않는 방식으로 `modeling`, `solver`, `output_requests` section을 추가한다.
4. Mesh 탭 상단에 model type selector를 추가한다.
5. Mesh 탭에 density/element/representation controls를 정리한다.
6. Analysis 탭에 run mode, bending setup, contact/friction, solver controls, output requests를 정리한다.
7. GUI preview를 model type에 따라 다르게 표시한다.
8. `input_data.json` export 결과를 저장하고 `code/sclas_self_check.py`로 contract regression을 막는다.
9. 보광 runner가 새 key를 소비하도록 `code/abaqus_runner.py`를 단계적으로 연결한다.
10. 연구실 PC에서 `scripts/run_self_check.bat`, `scripts/run_validation_suite.bat`, SmallSmoke 순서로 검증한다.

## 12. 보광에게 보낼 메시지 초안

```text
보광아, GUI에서 Mesh/Analysis 조건을 입력받아 Abaqus 자동화 스크립트로 넘길 변수 계약서 초안을 만들었습니다.

주요 확인 부탁:
1. model_type enum(full_3d / armour_equivalent / armour_core_equivalent) 사용 가능 여부
2. Mesh 변수(global seed, axial/circumferential divisions, element type 등) 중 Abaqus runner에서 실제로 받을 key
3. Contact/friction/preload/solver control 변수명과 default
4. output request list(UR2/RM2, S, CPRESS, COPEN, CSLIP 등) 확정
5. 모델 2/3에서 추가로 필요한 GUI 입력값

검토 후 구현 불가능하거나 변수명이 바뀌어야 하는 항목 알려주면 GUI와 input_data.json 구조에 반영하겠습니다.
```

## 13. 현재 주의사항

- 이 문서는 회의 영상의 음성 전사본 없이 작성한 초안이다.
- Abaqus 세부 설정값은 반드시 보광/현수 확인 후 확정한다.
- 현재 SCLAS 파이프라인은 GUI-Abaqus-ODB-result CSV까지 연결되어 있지만, contact closure/preload 물리는 아직 연구급 완료가 아니다.
- `CPRESS`와 slip이 실제로 nonzero로 나오는 reduced smoke case를 확보하기 전까지 문헌급 stick-slip 구현 완료로 표현하지 않는다.

