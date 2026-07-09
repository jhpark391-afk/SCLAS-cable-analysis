# SCLAS GUI-Backend Exchange Contract

작성일: 2026-07-09 KST

## 목적

이 문서는 GUI가 어떤 값을 `input_data.json`으로 만들고, Abaqus backend가 어떤 파일을 생성해 GUI로 돌려줘야 하는지 고정하기 위한 팀 내 계약서이다. 발표용 설명에서는 "GUI 입력 -> JSON 생성 -> Abaqus 자동화 코드 적용 -> ODB/CSV 결과 생성 -> GUI 결과 표시" 흐름으로 설명하면 된다.

## 전체 흐름

```text
GUI 입력값
-> job folder 생성
-> input_data.json / units_manifest.json / BACKEND_CONTRACT.md 저장
-> abaqus_runner.py / sclas_odb_extractor.py 복사
-> Abaqus backend가 input_data.json 읽기
-> CAE/INP/solver/ODB extraction 수행
-> result_data.csv / result_summary.json / manifest 생성
-> GUI가 결과 파일을 읽어 그래프와 summary 표시
```

## GUI가 반드시 쓰는 입력 파일

GUI job folder의 source of truth는 `input_data.json`이다.

주요 섹션:

| JSON section | 의미 |
|---|---|
| `metadata` | job id, GUI/frontend version, contract version |
| `geometry_mm` | 사용자가 입력한 기본 형상값과 `core_count` |
| `derived_geometry_mm` | GUI가 계산한 중심 반경, armour count limit, pitch length, effective length |
| `materials` | 8행 재료표: Conductor-Copper, Insulation-XLPE, Core Shield-HDPE, Filler-PP, Inner Sheath-HDPE, Armour-Steel, Bedding-PFR, Outer Sheath-HDPE |
| `armour` | armour wire radius/count, helix pitch angle, 계산된 pitch length |
| `mesh` | full 3D + solid wire 기준 mesh guide 값 |
| `mesh_controls` | component별 r/theta/z mesh control 구조 |
| `analysis_conditions` | 외압, 곡률, 마찰계수, 자동 effective length, solver/output 요청 |
| `backend_exchange_contract` | backend가 읽고 써야 하는 파일 목록과 흐름 |

## Pitch / effective length 계약

GUI에서 사용자가 직접 입력하는 값:

| GUI label | JSON key | 기본값 |
|---|---|---:|
| Core count | `geometry_mm.core_count` | `3` |
| Core helix pitch angle | `armour.core_lay_angle_deg` | `8.98 deg` |
| Inner armour helix pitch angle | `armour.inner_armour_lay_angle_deg` | `20.1 deg` |
| Outer armour helix pitch angle | `armour.outer_armour_lay_angle_deg` | `19.6 deg` |

GUI가 계산해서 넘기는 값:

```text
pitch_length_mm = 2*pi*center_radius_mm/tan(helix_pitch_angle_deg)
effective_length_mm = core_pitch_length_mm / core_count
```

주요 JSON key:

| JSON key | 의미 |
|---|---|
| `derived_geometry_mm.core_pitch_length_mm` | core helix pitch length |
| `derived_geometry_mm.inner_armour_pitch_length_mm` | inner armour pitch length |
| `derived_geometry_mm.outer_armour_pitch_length_mm` | outer armour pitch length |
| `analysis_conditions.effective_length_mm` | backend model length, GUI 자동 계산값 |
| `analysis_conditions.effective_length_source` | 현재 `core_pitch_length_mm_divided_by_core_count` |

주의: 현재 Abaqus backend의 실제 생성 모델은 기본 3-core full 3D 모델을 기준으로 안정화되어 있다. `core_count`는 JSON 계약에 포함되며, 추후 backend job 생성에서 core 개수까지 완전 변수화할 때 사용한다.

## Mesh z-direction 계약

팀 피드백에 따라 축방향 분할은 한 값으로 통일한다.

| GUI label | JSON key | 의미 |
|---|---|---|
| Axial `n_z` divisions | `mesh.axial_divisions` | 모든 component에 적용되는 전역 z-direction 분할수 |
| Filler z divisions | `mesh.filler_z_divisions` | backward compatibility key. GUI 입력은 없고 `mesh.axial_divisions`와 같은 값 |
| Filler z source | `mesh.filler_z_divisions_source` | `same_as_axial_divisions` |

즉, core / sheath / bedding / armour / filler 모두 같은 `mesh.axial_divisions`를 z 방향 기준으로 사용한다.

## Backend가 생성해야 하는 결과 파일

필수:

| 파일 | 역할 |
|---|---|
| `result_data.csv` | GUI 그래프용 moment-curvature 곡선 |

`result_data.csv` 필수 header:

```csv
curvature_1_per_m,moment_kn_m
```

권장/선택:

| 파일 | 역할 |
|---|---|
| `result_summary.json` | solver 상태, ODB 추출 상태, backend readiness, peak moment 등 scalar summary |
| `abaqus_mesh_manifest.json` | Abaqus model/mesh scaffold 상태와 생성 파일 목록 |
| `odb_extraction_summary.json` | ODB 추출 상세 요약 |
| `*.cae`, `*_mesh.inp`, `*.odb` | Abaqus 생성/해석 파일. Git에는 커밋하지 않음 |

## 구현 상태

- GUI는 `Design` 탭에서 core count와 helix pitch angle을 입력받고 pitch/effective length를 자동 표시한다.
- `Finite Element Analysis Setting` 탭의 effective length는 수동 입력이 아니라 자동 계산 표시값이다.
- GUI payload에는 `backend_exchange_contract`가 들어가므로 backend 담당자가 `input_data.json`만 열어도 파일 교환 규칙을 확인할 수 있다.
- Abaqus runner는 새 pitch/effective length key를 우선 사용하고, 구버전 payload와도 호환되도록 fallback 계산을 유지한다.
