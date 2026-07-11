# SCLAS GUI 변수 정리 및 코드 구조 지도

작성일: 2026-07-11 KST

## 1. 한 줄 결론

현재 GUI는 기능이 많이 붙어 있으므로, 앞으로는 변수를 아래 네 종류로 나누어 관리한다.

| 구분 | 의미 | GUI 표시 원칙 |
|---|---|---|
| User Input | 사용자가 직접 입력해야 하는 값 | 화면에 명확히 표시 |
| Derived | GUI가 계산하는 값 | 읽기 전용 확인값 또는 JSON preview에 표시 |
| Fixed / Backend Default | 현재 backend에서 고정하거나 숨겨 쓰는 값 | 일반 사용 화면에서는 숨김 |
| Output | backend가 계산 후 돌려주는 결과 | Results 탭과 summary에서 표시 |

보광이 피드백의 핵심은 "많이 보여주는 GUI"가 아니라 "필요한 입력만 남기고, 각 입력이 backend 어디에 쓰이는지 설명 가능한 GUI"로 정리하는 것이다.

## 1.1 2026-07-10 변수표 반영 메모

`SCLAS_변수_정리710.xlsx`의 약어는 `input_data.json`의 `sclas_710_variable_contract`에 그대로 기록한다. 다만 해당 파일의 `Roc=11`, `RoI=4` 기본값은 현재 GUI/backend 형상 수식에서 conductor radius가 insulation radius보다 커지는 충돌을 만들 수 있으므로, GUI 화면 기본값은 기존 물리적으로 유효한 `r_cond=4.00`, `r_ins=11.30`, `R_core=15.30`을 유지한다. 이 차이는 `sclas_710_variable_contract.note`에 명시한다.

## 2. 현재 남겨야 할 User Input 후보

아래 값들은 `C:\HELIX\Abaqus+_work\SCLAS_변수_정리710.xlsx`를 기준으로 다시 맞춘 값이다. 기존 backend 호환 key는 유지하되, `input_data.json`에는 `sclas_710_variable_contract`와 약어 alias도 같이 저장한다.

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
| Design | Helix Pitch Angle | Core helix pitch angle `alpha_core` / `CHA` | `core_lay_angle` | 9.00 | deg | `armour.core_lay_angle_deg` | SCLAS 710 기준 |
| Design | Helix Pitch Angle | Inner armour helix pitch angle `alpha_ia` / `IAHA` | `inner_lay_angle` | -20.1 | deg | `armour.inner_armour_lay_angle_deg` | 부호 보존, pitch 계산은 절댓값 사용 |
| Design | Helix Pitch Angle | Outer armour helix pitch angle `alpha_oa` | `outer_lay_angle` | 19.6 | deg | `armour.outer_armour_lay_angle_deg` | pitch angle 정의/부호 확인 |
| Design | Materials | 8-row material table | `table` | paper defaults | GPa, -, kg/m^3 | `materials[]` | 8개 material 기본값 확정 |
| Finite Element Analysis Setting | Analysis Structure Setup | Pressure `P` | `pressure` | 0.30 | MPa | `analysis_conditions.external_pressure_mpa`, `analysis_conditions.pressure_mpa` | SCLAS 710 `P` |
| Finite Element Analysis Setting | Analysis Structure Setup | Bend factor / curvature `BendFac` | `curvature` | 5.0e-5 | 1/m | `analysis_conditions.max_curvature_1_per_m`, `analysis_conditions.bend_factor` | 현재는 같은 GUI 입력으로 전달 |
| Finite Element Analysis Setting | Analysis Structure Setup | Friction coefficient `FrCo` / `mu` | `friction` | 0.30 | - | `analysis_conditions.friction_coefficient` | SCLAS 710 `FrCo` |
| Finite Element Analysis Setting | Mesh Setting Guide | Mesh input basis | `mesh_basis` | Division count | count/size | `mesh.mesh_input_basis` | 개수/목표 크기 입력 방식 선택 |
| Finite Element Analysis Setting | Mesh Setting Guide | z-axis divisions `ZAD` | `z_elem` | 60 | count | `mesh.axial_divisions` | 모든 component 공통 z 방향 |
| Finite Element Analysis Setting | Mesh Setting Guide | Core circumferential divisions `CCD` | `c_elem_core` | 20 | count | `mesh.core_circumferential_divisions` | core 전용 |
| Finite Element Analysis Setting | Mesh Setting Guide | Bedding/Sheath circumferential divisions `BSCD` | `c_elem_bedding_sheath` | 80 | count | `mesh.bedding_sheath_circumferential_divisions` | inner sheath, bedding, outer sheath |
| Finite Element Analysis Setting | Mesh Setting Guide | Armour circumferential divisions `ACD` | `c_elem_armour` | 3 | count | `mesh.armour_circumferential_divisions` | armour wire 단면 |
| Finite Element Analysis Setting | Mesh Setting Guide | Inner sheath `n_r` divisions | `r_elem_inner_sheath` | 3 | count | `mesh.inner_sheath_radial_divisions` | radial division 기준 |
| Finite Element Analysis Setting | Mesh Setting Guide | Bedding/Sheath radial divisions `BSRD` | `r_elem_bedding` | 3 | count | `mesh.bedding_radial_divisions`, `mesh.bedding_sheath_radial_divisions` | SCLAS 710 alias |
| Finite Element Analysis Setting | Mesh Setting Guide | Outer sheath `n_r` divisions | `r_elem_outer_sheath` | 3 | count | `mesh.outer_sheath_radial_divisions` | radial division 기준 |
| Finite Element Analysis Setting | Mesh Setting Guide | Target axial size | `z_size` | 5.85 | mm | `mesh.target_sizes_mm.axial_mm` | size mode에서 `mesh.axial_divisions`로 환산 |
| Finite Element Analysis Setting | Mesh Setting Guide | Target core/sheath circumferential size | `c_size_core` | 13.50 | mm | `mesh.target_sizes_mm.core_sheath_circumferential_mm` | size mode에서 `mesh.core_circumferential_divisions`로 환산 |
| Finite Element Analysis Setting | Mesh Setting Guide | Target armour circumferential size | `c_size_armour` | 1.60 | mm | `mesh.target_sizes_mm.armour_circumferential_mm` | size mode에서 `mesh.armour_circumferential_divisions`로 환산 |
| Finite Element Analysis Setting | Mesh Setting Guide | Target inner sheath radial size | `r_size_inner_sheath` | 1.50 | mm | `mesh.target_sizes_mm.inner_sheath_radial_mm` | size mode에서 `mesh.inner_sheath_radial_divisions`로 환산 |
| Finite Element Analysis Setting | Mesh Setting Guide | Target bedding radial size | `r_size_bedding` | 0.60 | mm | `mesh.target_sizes_mm.bedding_radial_mm` | size mode에서 `mesh.bedding_radial_divisions`로 환산 |
| Finite Element Analysis Setting | Mesh Setting Guide | Target outer sheath radial size | `r_size_outer_sheath` | 1.50 | mm | `mesh.target_sizes_mm.outer_sheath_radial_mm` | size mode에서 `mesh.outer_sheath_radial_divisions`로 환산 |
| Finite Element Analysis Setting | Mesh Setting Guide | Filler short line divisions `FD1` | `filler_short_line_elem` | 2 | count | `mesh.filler_profile_divisions.short_line` | filler profile seed |
| Finite Element Analysis Setting | Mesh Setting Guide | Filler long line divisions `FD2` | `filler_long_line_elem` | 2 | count | `mesh.filler_profile_divisions.long_line` | filler profile seed |
| Finite Element Analysis Setting | Mesh Setting Guide | Filler short arc divisions `FD3` | `filler_short_arc_elem` | 4 | count | `mesh.filler_profile_divisions.short_arc` | filler profile seed |
| Finite Element Analysis Setting | Mesh Setting Guide | Filler long arc divisions `FD4` | `filler_long_arc_elem` | 6 | count | `mesh.filler_profile_divisions.long_arc` | filler profile seed |

## 3. 계산값으로만 둘 값

아래 값들은 사용자가 직접 입력하면 안 되고, GUI가 계산해서 보여주거나 JSON에 넣는다.

| 값 | 계산 방식 | JSON path | GUI 처리 |
|---|---|---|---|
| Core center radius | `2*sqrt(3)/3 * R_core` | `derived_geometry_mm.core_center_radius_mm` | 입력창 없음 |
| Armour count limit | `floor(pi/asin(r_wire/R_center))` | `derived_geometry_mm.*_wire_count_limit` | spinbox maximum으로만 사용 |
| Core raw pitch length | Menard-Cartraud 2023 Eq. (2): `p = 2*pi*R_h/tan(alpha_core)` | `derived_geometry_mm.core_pitch_length_mm` | 읽기 전용 확인 |
| Inner armour raw pitch length | Eq. (2): `p = 2*pi*R_h/tan(alpha_ia)` | `derived_geometry_mm.inner_armour_input_pitch_length_mm` | 읽기 전용 확인 |
| Outer armour raw pitch length | Eq. (2): `p = 2*pi*R_h/tan(alpha_oa)` | `derived_geometry_mm.outer_armour_input_pitch_length_mm` | 읽기 전용 확인 |
| Common period / Effective length | Eq. (3): `l = k_j*p_j/n_j`, core period 기준 | `analysis_conditions.effective_length_mm` | Analysis 탭에서 읽기 전용 |
| Armour period multipliers | `round(L_eff*n_armour/p_raw)` | `derived_geometry_mm.*_period_multiplier` | GUI가 자동 선택 |
| Armour backend pitch length | `L_eff*n_armour/k_armour` | `armour.*_backend_pitch_length_mm` | backend가 우선 사용 |
| Filler z divisions | `mesh.axial_divisions`와 동일 | `mesh.filler_z_divisions` | 별도 입력 없음 |
| Size-mode resolved mesh counts | `ceil(length_or_arc_or_thickness / target_size)` 후 spinbox 범위로 clamp | `mesh.*_divisions` | 사용자는 size 입력, backend는 기존 count key 사용 |
| Equivalent EI estimate | material + conductor/core geometry 기반 GUI estimate | `equivalent_properties.core_equivalent_EI_N_m2` | 참고값, 연구 결과 아님 |

## 4. 숨기거나 고정해야 할 값

아래 값들은 일반 사용자가 선택하게 하면 오히려 혼란이 커질 가능성이 높다.

| 항목 | 현재 상태 | 정리 방향 |
|---|---|---|
| `mesh.model_strategy` | backend 기본 `full_3d_segment` | 계속 숨김 |
| `mesh.armour_model` | backend 기본 `solid_wire` | 계속 숨김 |
| `mesh.requested_element_type` | GUI 표시값 `C3D8` | 선택형 combo가 아니라 고정 표시 |
| `mesh.filler_z_divisions` | 호환 key로 JSON에 남음 | 화면에서는 숨김 |
| `analysis_conditions.residual_contact_pressure_mpa` | hidden widget | 보광/현수 calibration 단계 전까지 숨김 |
| `analysis_conditions.max_twist_rad_per_m` | future/coupled-load 기본값 | Analysis 탭 화면에서 숨김 |
| `analysis_conditions.max_axial_strain` | future/coupled-load 기본값 | Analysis 탭 화면에서 숨김 |
| `analysis_conditions.radial_compression_ratio` | future/coupled-load 기본값 | Analysis 탭 화면에서 숨김 |
| solver increments | JSON fixed values | 전문가 모드 전까지 숨김 |
| output request field list | JSON fixed list | backend 구현 기준으로 유지 |
| run mode flags | backend 실행 모드 내부값 | 일반 변수표에서 분리 |

현재 GUI는 `Abaqus element type`을 `C3D8` 고정 표시로 단순화했다. `C3D8R`의 `R`은 reduced integration을 의미하므로 현재 발표/기본 계약값으로 쓰지 않는다. `C3D4`, `B31` 선택지는 사용자가 잘못 고를 수 있으므로 화면에서 제거했다. 내부 backend는 필요하면 solid/beam element를 자체적으로 결정해야 한다.

## 5. 보광이와 회의할 때 맞춰야 할 질문

### 형상 기본값

1. `r_cond = 4.00 mm`, `r_ins = 11.30 mm`, `R_core = 15.30 mm`가 최종 모델 기준과 맞는가?
2. `core_count = 3`은 앞으로도 GUI 기본값으로 유지해도 되는가?
3. `t_is = 4.50 mm`, `t_bedding = 0.60 mm`, `t_os = 4.50 mm`가 맞는가?
4. inner armour `r_ia = 2.00 mm`, `n_ia = 55`가 맞는가?
5. outer armour `r_oa = 2.00 mm`, `n_oa = 63`이 맞는가?

### pitch / effective length

1. 사용자는 pitch length가 아니라 pitch angle을 입력하는 것이 맞는가?
2. pitch length 계산식 `2*pi*R_h/tan(alpha)`가 보광 모델의 angle 정의와 같은가?
3. 공통 period 자동 선택식 `l = k_j*p_j/n_j`가 보광 자동화 코드와 같은가?
4. inner armour pitch 부호는 backend 내부에서 음수로 쓰는 것이 맞는가?
5. effective length를 core period 기준으로 두고 armour pitch를 period-matched 값으로 보정하는 것이 맞는가?

### mesh

1. `ZAD=mesh.axial_divisions` 하나가 모든 component의 z direction에 적용되는 것이 맞는가?
2. filler 전용 z division은 완전히 제거하고 `ZAD`와 동일하게 봐도 되는가?
3. `CCD`와 `BSCD`를 backend가 실제로 분리 적용할지, 아니면 당분간 `core_circumferential_divisions`만 사용할지 확인한다.
4. `ACD=3`처럼 4의 배수가 아닌 armour circumferential division도 backend mesh에서 허용되는지 확인한다.
5. `FD1~FD4` filler profile divisions를 backend에서 어떤 edge/arc 순서로 매핑하는지 확인한다.
6. `Abaqus element type = C3D8` 고정 표시가 보광 backend의 full 3D solid-wire workflow와 맞는가?
7. circumferential division은 4의 배수를 권장만 하고 강제하지 않는 것이 맞는가?
8. 사용자가 mesh size와 mesh count를 모두 입력 방식으로 선택할 수 있게 하는 현재 방식이 맞는가?

### analysis

1. `P=0.30 MPa`가 생산 잔여 압력/외압 중 어느 물리량인지 backend 명명과 최종 정리한다.
2. `BendFac=5.0e-5`가 `max_curvature_1_per_m`와 같은 의미인지, 또는 별도 curve factor인지 확인한다.
3. friction coefficient `FrCo=0.30`을 모든 contact pair에 공통 적용하는 것이 맞는가?
4. `conStiff`는 아직 null로 두고 backend 내부/default로 처리해도 되는가?
5. residual contact pressure `0.30 MPa`는 계속 숨겨두는가?
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
  -> parse_geometry()에서 Menard-Cartraud 2023 Eq. (2)로 core_pitch_length_mm 계산
  -> Eq. (3) 기준 effective_length_mm = core_pitch_length_mm / core_count
  -> inner/outer armour의 integer multiplier k를 자동 선택
  -> armour.inner/outer_backend_pitch_length_mm를 period-matched 값으로 산출
  -> build_payload()에서 armour.*_pitch_mm, analysis_conditions.effective_length_mm 저장
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

```text
Mesh 탭 Target size mode
  -> self.mesh_inputs["mesh_basis"] = size
  -> z_size / c_size_core / c_size_armour / r_size_* 입력
  -> mesh_request_values()에서 target size를 resolved count로 환산
  -> build_payload()에서 mesh.target_sizes_mm과 mesh.*_divisions를 둘 다 저장
  -> backend는 기존 count key를 그대로 사용하고, target size는 추적/검토용으로 보존
```

## 8. 다음 cleanup 제안

2026-07-09 기준으로 GUI 3번 탭도 단순화했다.

1. Analysis 탭은 `Effective length`, `Loading cycles`, `Result points`만 직접 표시한다.
2. `twist`, `axial_strain`, `radial_compression`은 payload default로 남기되 화면에서는 숨긴다.
3. `Research Scope / Local Behavior` 체크박스 묶음은 화면에서 제거하고, payload에는 bending/pressure 중심 scope만 남긴다.
4. Backend mode는 `FAST GUI preview`, `Export job package only`, `Run local/shared-folder command`만 화면에 표시한다.
5. SSH/scp 원격 설정은 코드 호환용으로 남기되 일반 GUI 화면에서는 숨긴다.
6. Run Controls에 `Import Backend JSON` 버튼을 추가해 `input_data.json`을 GUI 값으로 다시 불러오는 정보 교환 루프를 명확히 했다.

남은 cleanup 후보는 다음과 같다.

1. Derived Pitch / Length 박스는 Design 탭에 남기되 "calculated, not user input" 문구를 추가하거나 JSON preview 쪽으로 옮긴다.
2. 보광이 엑셀의 최종 기본값을 받아 Design/FEA Setting 탭 기본값과 변수 register를 다시 맞춘다.
3. `docs/SCLAS_GUI_VARIABLE_REGISTER_20260708.xlsx`에 `User Input / Derived / Hidden Backend Default / Output` 판정 열을 추가한다.

이후 코드 삭제는 backend가 실제로 더 이상 읽지 않는 것이 확인된 뒤에 진행하는 것이 안전하다.
