# SCLAS GUI 변수 정리 및 코드 구조 지도

작성일: 2026-07-09 KST

## 1. 한 줄 결론

현재 GUI는 기능이 많이 붙어 있으므로, 앞으로는 변수를 아래 네 종류로 나누어 관리한다.

| 구분 | 의미 | GUI 표시 원칙 |
|---|---|---|
| User Input | 사용자가 직접 입력해야 하는 값 | 화면에 명확히 표시 |
| Derived | GUI가 계산하는 값 | 읽기 전용 확인값 또는 JSON preview에 표시 |
| Fixed / Backend Default | 현재 backend에서 고정하거나 숨겨 쓰는 값 | 일반 사용 화면에서는 숨김 |
| Output | backend가 계산 후 돌려주는 결과 | Results 탭과 summary에서 표시 |

보광이 피드백의 핵심은 "많이 보여주는 GUI"가 아니라 "필요한 입력만 남기고, 각 입력이 backend 어디에 쓰이는지 설명 가능한 GUI"로 정리하는 것이다.

## 2. 현재 남겨야 할 User Input 후보

아래 값들은 현재 사용자가 직접 입력해도 의미가 있는 값이다. 다만 기본값은 보광이와 회의해서 다시 확정해야 한다.

| Tab | Section | GUI Label | Code key | Default | Unit | JSON path | 확인 필요 |
|---|---|---|---|---:|---|---|---|
| Design | Core Section | Conductor radius `r_cond` | `r_cond` | 4.00 | mm | `geometry_mm.conductor_radius_mm` | 논문/보광 모델 기준 |
| Design | Core Section | Insulation radius `r_ins` | `r_insu` | 11.30 | mm | `geometry_mm.insulation_radius_mm` | 논문/보광 모델 기준 |
| Design | Core Section | Core outer radius `R_core` | `roc` | 15.30 | mm | `geometry_mm.core_outer_radius_mm` | 논문/보광 모델 기준 |
| Design | Core Section | Core count `n_core` | `core_count` | 3 | count | `geometry_mm.core_count` | 현재 3-core 고정 모델과 맞는지 |
| Design | Sheath / Bedding | Inner sheath `t_is` | `tis` | 4.50 | mm | `geometry_mm.inner_sheath_thickness_mm` | 보광 모델 기준 |
| Design | Sheath / Bedding | Bedding thickness `t_bedding` | `bedding_thickness` | 0.60 | mm | `geometry_mm.bedding_thickness_mm` | armour-armour 사이 bedding 정의 확인 |
| Design | Sheath / Bedding | Outer sheath `t_os` | `tos` | 4.50 | mm | `geometry_mm.outer_sheath_thickness_mm` | 보광 모델 기준 |
| Design | Armour | Inner armour radius `r_ia` | `r_ia` | 2.00 | mm | `armour.inner_wire_radius_mm` | 보광 모델 기준 |
| Design | Armour | Inner armour number `n_ia` | `no_ia` | 55 | count | `armour.inner_wire_count` | 55 default 확정 필요 |
| Design | Armour | Outer armour radius `r_oa` | `r_oa` | 2.00 | mm | `armour.outer_wire_radius_mm` | 보광 모델 기준 |
| Design | Armour | Outer armour number `n_oa` | `no_oa` | 63 | count | `armour.outer_wire_count` | 63 default 확정 필요 |
| Design | Helix Pitch Angle | Core helix pitch angle `alpha_core` | `core_lay_angle` | 8.98 | deg | `armour.core_lay_angle_deg` | pitch angle 정의/부호 확인 |
| Design | Helix Pitch Angle | Inner armour helix pitch angle `alpha_ia` | `inner_lay_angle` | 20.1 | deg | `armour.inner_armour_lay_angle_deg` | pitch angle 정의/부호 확인 |
| Design | Helix Pitch Angle | Outer armour helix pitch angle `alpha_oa` | `outer_lay_angle` | 19.6 | deg | `armour.outer_armour_lay_angle_deg` | pitch angle 정의/부호 확인 |
| Design | Materials | 8-row material table | `table` | paper defaults | GPa, -, kg/m^3 | `materials[]` | 8개 material 기본값 확정 |
| Finite Element Analysis Setting | Analysis Structure Setup | External pressure load | `pressure` | 40.00 | MPa | `analysis_conditions.external_pressure_mpa` | 실제 해석 기본 외압인지 |
| Finite Element Analysis Setting | Analysis Structure Setup | Target curvature `kappa` | `curvature` | 0.08 | 1/m | `analysis_conditions.max_curvature_1_per_m` | 곡률 기본값/단위 확인 |
| Finite Element Analysis Setting | Analysis Structure Setup | Friction coefficient `mu` | `friction` | 0.22 | - | `analysis_conditions.friction_coefficient` | 마찰계수 기본값 확인 |
| Finite Element Analysis Setting | Mesh Setting Guide | Global axial `n_z` divisions | `z_elem` | 40 | count | `mesh.axial_divisions` | 모든 component 공통 적용 확정 |
| Finite Element Analysis Setting | Mesh Setting Guide | Core/Sheath `n_theta` divisions | `c_elem_core` | 24 | count | `mesh.core_circumferential_divisions` | core/sheath/bedding 공통인지 |
| Finite Element Analysis Setting | Mesh Setting Guide | Armour `n_theta` divisions | `c_elem_armour` | 8 | count | `mesh.armour_circumferential_divisions` | armour solid wire 기준 |
| Finite Element Analysis Setting | Mesh Setting Guide | Inner sheath `n_r` divisions | `r_elem_inner_sheath` | 3 | count | `mesh.inner_sheath_radial_divisions` | radial division 기준 |
| Finite Element Analysis Setting | Mesh Setting Guide | Bedding `n_r` divisions | `r_elem_bedding` | 1 | count | `mesh.bedding_radial_divisions` | radial division 기준 |
| Finite Element Analysis Setting | Mesh Setting Guide | Outer sheath `n_r` divisions | `r_elem_outer_sheath` | 3 | count | `mesh.outer_sheath_radial_divisions` | radial division 기준 |

## 3. 계산값으로만 둘 값

아래 값들은 사용자가 직접 입력하면 안 되고, GUI가 계산해서 보여주거나 JSON에 넣는다.

| 값 | 계산 방식 | JSON path | GUI 처리 |
|---|---|---|---|
| Core center radius | `2*sqrt(3)/3 * R_core` | `derived_geometry_mm.core_center_radius_mm` | 입력창 없음 |
| Armour count limit | `floor(pi/asin(r_wire/R_center))` | `derived_geometry_mm.*_wire_count_limit` | spinbox maximum으로만 사용 |
| Core pitch length | `2*pi*R_core_center/tan(alpha_core)` | `derived_geometry_mm.core_pitch_length_mm` | 읽기 전용 확인 |
| Inner armour pitch length | `2*pi*R_inner_armour_center/tan(alpha_ia)` | `derived_geometry_mm.inner_armour_pitch_length_mm` | 읽기 전용 확인 |
| Outer armour pitch length | `2*pi*R_outer_armour_center/tan(alpha_oa)` | `derived_geometry_mm.outer_armour_pitch_length_mm` | 읽기 전용 확인 |
| Effective length | `core_pitch_length_mm / core_count` | `analysis_conditions.effective_length_mm` | Analysis 탭에서 읽기 전용 |
| Filler z divisions | `mesh.axial_divisions`와 동일 | `mesh.filler_z_divisions` | 별도 입력 없음 |
| Equivalent EI estimate | material + conductor/core geometry 기반 GUI estimate | `equivalent_properties.core_equivalent_EI_N_m2` | 참고값, 연구 결과 아님 |

## 4. 숨기거나 고정해야 할 값

아래 값들은 일반 사용자가 선택하게 하면 오히려 혼란이 커질 가능성이 높다.

| 항목 | 현재 상태 | 정리 방향 |
|---|---|---|
| `mesh.model_strategy` | backend 기본 `full_3d_segment` | 계속 숨김 |
| `mesh.armour_model` | backend 기본 `solid_wire` | 계속 숨김 |
| `mesh.filler_z_divisions` | 호환 key로 JSON에 남음 | 화면에서는 숨김 |
| `analysis_conditions.residual_contact_pressure_mpa` | hidden widget | 보광/현수 calibration 단계 전까지 숨김 |
| solver increments | JSON fixed values | 전문가 모드 전까지 숨김 |
| output request field list | JSON fixed list | backend 구현 기준으로 유지 |
| run mode flags | backend 실행 모드 내부값 | 일반 변수표에서 분리 |

특히 `Abaqus element type`은 확인이 필요하다. 현재 GUI에는 `C3D8R`, `C3D4`, `B31` option이 남아 있는데, full 3D + solid wire가 고정 방향이면 사용자가 `B31`을 고르게 두는 것이 맞는지 보광이와 확인해야 한다. 확인 후에는 `C3D8R` 고정 표시 또는 숨김으로 줄이는 것이 더 깔끔하다.

## 5. 보광이와 회의할 때 맞춰야 할 질문

### 형상 기본값

1. `r_cond = 4.00 mm`, `r_ins = 11.30 mm`, `R_core = 15.30 mm`가 최종 모델 기준과 맞는가?
2. `core_count = 3`은 앞으로도 GUI 기본값으로 유지해도 되는가?
3. `t_is = 4.50 mm`, `t_bedding = 0.60 mm`, `t_os = 4.50 mm`가 맞는가?
4. inner armour `r_ia = 2.00 mm`, `n_ia = 55`가 맞는가?
5. outer armour `r_oa = 2.00 mm`, `n_oa = 63`이 맞는가?

### pitch / effective length

1. 사용자는 pitch length가 아니라 pitch angle을 입력하는 것이 맞는가?
2. pitch length 계산식 `2*pi*R/tan(alpha)`가 보광 모델의 angle 정의와 같은가?
3. inner armour pitch 부호는 backend 내부에서 음수로 쓰는 것이 맞는가?
4. effective length를 `core_pitch_length / core_count`로 자동 설정하는 것이 맞는가?

### mesh

1. `mesh.axial_divisions` 하나가 모든 component의 z direction에 적용되는 것이 맞는가?
2. filler 전용 z division은 완전히 제거해도 되는가?
3. `Core/Sheath n_theta`를 core, inner sheath, bedding, outer sheath에 공통 적용해도 되는가?
4. `Abaqus element type`을 사용자가 고르게 할 것인가, `C3D8R`로 고정할 것인가?
5. sweep method, medial axis, advancing front 같은 mesh method는 GUI에서 고를 필요가 있는가, backend 고정값인가?

### analysis

1. 외압 기본값 `40 MPa`가 실제 baseline인가?
2. target curvature `0.08 1/m`가 baseline인가?
3. friction coefficient `0.22`가 baseline인가?
4. residual contact pressure `0.30 MPa`는 계속 숨겨두는가?
5. twist, axial strain, radial compression은 지금 GUI에서 보여줄 필요가 있는가, 아니면 후속 연구 탭으로 숨길 것인가?

## 6. GUI 코드 구조 지도

현재 GUI 핵심 파일은 `code/sclas_remote_gui.py`이다.

| 코드 위치 | 역할 |
|---|---|
| `BackendWorker.run()` around line 253 | 버튼 실행 후 FAST/local/remote backend 실행 분기 |
| `BackendWorker.load_backend_result()` around line 368 | backend 결과 파일을 읽어 GUI로 돌려줌 |
| `create_job_package()` around line 408 | job folder 생성, `input_data.json`, `BACKEND_CONTRACT.md`, runner 복사 |
| `build_design_tab()` around line 1314 | Design 탭 UI 생성, `self.inputs` 정의 |
| `build_mesh_tab()` around line 1541 | Finite Element Analysis Setting 탭의 해석 구조/mesh guide UI 생성 |
| `ensure_analysis_condition_widgets()` around line 1694 | pressure, curvature, friction, effective length 등 `self.cond` 생성 |
| `build_analysis_tab()` around line 1729 | backend mode, job root, run/create controls, results 조건 UI 생성 |
| `parse_geometry()` around line 2133 | GUI 입력값을 radii, pitch length, effective length 등으로 계산 |
| `build_payload()` around line 2266 | 모든 입력/계산값을 `input_data.json` 구조로 조립 |
| `build_numerical_model_notes()` around line 2504 | contact/interface/periodic cell 관련 backend note 생성 |
| `collect_materials()` around line 2596 | material table 8행을 `materials[]`로 변환 |
| `compute_equivalent_properties()` around line 2613 | GUI 참고용 equivalent EI 계산 |
| `install_input_preview_autorefresh()` around line 2674 | 입력값 변경 시 preview 자동 갱신 연결 |
| `refresh_input_preview()` around line 2770 | 현재 `input_data.json` preview 표시 |
| `apply_backend_payload_to_gui()` around line 3568 | 기존 backend JSON을 GUI widget 값으로 역매핑 |
| `load_csv()` around line 3665 | key,value CSV를 GUI 입력칸으로 불러옴 |
| `generate_mesh_preview()` around line 4447 | GUI 값 기반 mesh guide preview 생성 |
| `import_inp_mesh_dialog()` around line 4601 | 실제 Abaqus `.inp`를 읽어 mesh를 검토 |

보조 파일:

| 파일 | 역할 |
|---|---|
| `code/sclas_backend_gui_bridge.py` | backend JSON을 GUI 값으로 매핑하는 pure Python helper |
| `code/abaqus_runner.py` | `input_data.json`을 읽어 Abaqus model/deck/result 생성 |
| `docs/guides/SCLAS_GUI_BACKEND_EXCHANGE_CONTRACT_KR.md` | GUI/backend 파일 교환 계약 |
| `docs/SCLAS_GUI_VARIABLE_REGISTER_20260708.xlsx` | 변수 register 엑셀 |

## 7. 값이 실제로 흘러가는 방식

```text
사용자 입력
  -> self.inputs / self.mesh_inputs / self.cond
  -> parse_geometry()
  -> build_payload()
  -> input_data.json
  -> abaqus_runner.py normalize_payload()
  -> Abaqus CAE/INP/solver/ODB
  -> result_data.csv / result_summary.json
  -> GUI Results tab
```

예시:

```text
Design 탭 Bedding thickness
  -> self.inputs["bedding_thickness"]
  -> parse_geometry()에서 bedding_outer_radius_mm 계산
  -> build_payload()에서 geometry_mm.bedding_thickness_mm 저장
  -> abaqus_runner.py에서 bedding solid geometry 생성에 사용
```

```text
Design 탭 Core helix pitch angle
  -> self.inputs["core_lay_angle"]
  -> parse_geometry()에서 core_pitch_length_mm 계산
  -> effective_length_mm = core_pitch_length_mm / core_count
  -> build_payload()에서 armour.core_pitch_mm, analysis_conditions.effective_length_mm 저장
  -> abaqus_runner.py에서 BaseSolidExtrude pitch/depth에 사용
```

```text
Mesh 탭 Global axial n_z divisions
  -> self.mesh_inputs["z_elem"]
  -> build_payload()에서 mesh.axial_divisions 저장
  -> mesh_controls 모든 component z.count에 같은 값 저장
  -> filler_z_divisions도 같은 값으로 mirror
  -> abaqus_runner.py에서 seedEdgeByNumber axial division에 사용
```

## 8. 다음 cleanup 제안

가장 먼저 정리할 후보는 다음 세 가지다.

1. `Abaqus element type` combo를 실제 backend 기준으로 고정 또는 축소한다.
2. Analysis 탭의 `twist`, `axial_strain`, `radial_compression`을 당장 backend 검증에 쓰지 않으면 advanced/future 영역으로 숨긴다.
3. Derived Pitch / Length 박스는 Design 탭에 남기되 "calculated, not user input" 문구를 추가하거나 JSON preview 쪽으로 옮긴다.

이 세 가지는 코드 삭제보다 먼저 보광이와 기본값/필요성을 확인한 뒤 진행하는 것이 안전하다.

