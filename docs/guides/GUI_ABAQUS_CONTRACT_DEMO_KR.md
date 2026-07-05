# GUI-Abaqus 입력 계약 데모 정리

작성일: 2026-07-05

## 목적

보광이의 Abaqus 수렴 결과를 기다리지 않고, 지호 담당 GUI 범위에서 먼저 검증할 수 있는 부분을 정리했다.

GUI 담당 범위는 다음 네 가지다.

1. 코어 반지름 변환 확인
2. Armour 개수 입력/Auto 확인
3. Mesh 설정과 해석 조건을 Abaqus 입력 계약으로 전달
4. Backend 결과 폴더 진단 루틴 확인

## 완료 범위

### 1. 코어 반지름 변환

GUI에서 RoC 15.3, 20, 25 mm 케이스를 모두 확인했다.

| Case | Core radius RoC | Converted CoC |
|---|---:|---:|
| RoC15.3 | 15.3 mm | 17.667 mm |
| RoC20.0 | 20.0 mm | 23.094 mm |
| RoC25.0 | 25.0 mm | 28.868 mm |

### 2. Armour 개수 입력/Auto

각 RoC 케이스마다 Auto와 manual 입력을 모두 확인했다.

| Case | Inner armour | Outer armour |
|---|---:|---:|
| RoC15.3 Auto | 62 | 70 |
| RoC15.3 Manual | 55 | 63 |
| RoC20.0 Auto | 78 | 86 |
| RoC20.0 Manual | 55 | 63 |
| RoC25.0 Auto | 95 | 103 |
| RoC25.0 Manual | 55 | 63 |

모든 케이스에서 GUI payload와 저장된 `input_data.json` 값이 일치했다.

### 3. Mesh / Analysis 입력 계약

GUI에서 다음 값들이 `input_data.json`으로 전달되는 것을 확인했다.

Mesh 입력:
- Abaqus element type
- model strategy
- armour model
- axial divisions
- core circumferential divisions
- armour circumferential divisions
- inner sheath / bedding / outer sheath radial divisions

Analysis 입력:
- effective length
- external pressure
- max curvature
- max twist
- max axial strain
- radial compression ratio
- loading cycles
- result steps

접촉 조건인 friction, residual contact pressure, contact beta는 지호 GUI 입력 범위에서 제외하고 backend 기본값으로 유지했다.

### 4. Backend 결과 진단

`C:\HELIX\Abaqus+_work\for_test` 폴더를 GUI/diagnostics 흐름으로 진단했다.

진단 결과 현재 backend job은 성공 결과가 아니다.

첫 번째 blocking error:

```text
Cable_Bending.dat:1269 ***ERROR: DEGREE OF FREEDOM 2 DOES NOT EXIST FOR NODE 1 (ASSEMBLY). IT HAS
```

따라서 현재 병목은 GUI 입력 계약이 아니라 Abaqus backend의 coupling / DOF / boundary condition 정리다.

## 데모 산출물

로컬 데모 산출물 위치:

```text
C:\Users\user\Documents\SCLAS-cable-analysis\jobs\SCLAS_jobs\gui_contract_demo_20260705_180210
```

주요 파일:
- `GUI_ABAQUS_CONTRACT_DEMO_SUMMARY.txt`
- `demo_manifest.json`
- `01_design_geometry.png`
- `02_mesh_settings.png`
- `03_analysis_input_preview.png`
- `04_input_preview_panel.png`
- `backend_for_test_diagnostics.md`
- `backend_for_test_diagnostics.json`

주의: 위 데모 폴더는 generated job artifact이므로 Git commit 대상이 아니다.

## 결론

지호 담당 GUI 선행 목표는 완료된 상태다.

현재 GUI는 geometry, mesh, analysis 조건을 입력받고 backend가 읽을 수 있는 `input_data.json` job package로 변환한다. 또한 생성될 Abaqus 입력값을 `Abaqus Input Preview` 패널에서 확인할 수 있고, 외부 backend result folder의 첫 blocking error를 진단할 수 있다.

다음 병목은 보광이 backend 쪽의 실제 Abaqus 해석 수렴과 ODB 기반 `result_data.csv` 생성이다.
