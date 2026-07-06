# 보광 인수인계 - GUI/Abaqus 연결 및 CurveV0 검증

작성일: 2026-07-06 KST  
저장소 경로: `C:\Users\user\Documents\SCLAS-cable-analysis`

## 1. 먼저 볼 파일

보광이는 같은 원격 PC에서 아래 파일을 먼저 열면 됩니다.

```text
C:\Users\user\Documents\SCLAS-cable-analysis\docs\internal_handoff\BOGWANG_GUI_ABAQUS_HANDOFF_20260706_KR.md
C:\Users\user\Documents\SCLAS-cable-analysis\docs\internal_handoff\CURRENT_HANDOFF_KR.md
C:\Users\user\Documents\SCLAS-cable-analysis\code\abaqus_runner.py
C:\Users\user\Documents\SCLAS-cable-analysis\code\sclas_odb_extractor.py
C:\Users\user\Documents\SCLAS-cable-analysis\scripts\run_lab_abaqus_smoke.ps1
C:\Users\user\Documents\SCLAS-cable-analysis\scripts\run_curve_v0_sweep.ps1
```

## 2. 현재까지 연결된 구조

GUI에서 사용자가 입력한 값은 `input_data.json`으로 저장되고, Abaqus backend는 이 값을 읽어 모델 생성, solver 실행, ODB 추출을 진행합니다.

현재 연결 확인이 끝난 흐름은 다음과 같습니다.

```text
GUI 입력값
-> input_data.json
-> code\abaqus_runner.py
-> Abaqus job submit
-> Cable_Bending.odb 생성
-> code\sclas_odb_extractor.py
-> result_data.csv / result_summary.json 생성
```

## 3. 검증 완료 결과

### SmallSmoke

검증 폴더:

```text
C:\Users\user\Documents\SCLAS-cable-analysis\jobs\SCLAS_jobs\small_smoke_20260706_222907
```

검증 결과:

```text
result_summary.json.source = SCLAS_ABAQUS_ODB_EXTRACTOR
odb_extraction.status = extracted
odb_extraction.rows_written = 25
```

### CurveV0 endpoint sweep

검증 폴더:

```text
C:\Users\user\Documents\SCLAS-cable-analysis\jobs\SCLAS_jobs\curve_v0_sweep_20260706_223250
```

검증 결과:

```text
factor = -0.1, -0.05, 0, 0.05, 0.1
parent result_data.csv rows = 5
parent result_summary.json.source = SCLAS_CURVE_V0_ENDPOINT_SWEEP
endpoint_sweep_validation.all_child_jobs_validated = true
```

각 child job은 모두 다음 조건을 만족했습니다.

```text
result_summary.json.source = SCLAS_ABAQUS_ODB_EXTRACTOR
odb_extraction.status = extracted
odb_extraction.rows_written = 25
```

## 4. 중요한 해석 주의사항

이번 성공은 최종 연구용 full cable contact model 검증이 아니라, GUI와 Abaqus backend 사이의 bridge 계약 검증입니다.

현재 reduced smoke 조건에서는 다음이 의도적으로 단순화되어 있습니다.

```text
contact_pair_status = skipped_reduced_smoke
boundary_condition_mode = reduced_smoke_direct_end_rotation
```

따라서 이 결과는 다음 의미로 보고해야 합니다.

```text
맞는 표현:
GUI 입력값이 Abaqus backend로 전달되고, Abaqus ODB 기반 result_data.csv가 생성되는 end-to-end bridge가 검증되었다.

피해야 할 표현:
최종 연구용 접촉/마찰 full cable 모델이 완성되었다.
```

## 5. 영제 형 피드백 반영 상태

반영됨:

- 사용자가 입력한 mesh division 값에 따라 GUI mesh preview가 변합니다.
- Abaqus `.inp` 파일을 읽어 part-colored mesh preview를 표시하는 초안 기능이 있습니다.
- GUI 입력값 기반으로 `mesh` 계약에 `z`, `theta`, `r`, `filler_z_divisions`가 전달됩니다.
- `filler_divisions` / `filler_z_elem`이 GUI와 backend bridge 계약에 포함되었습니다.
- material table은 `E`, `ν`, `ρ (kg/m³)` 기호를 사용합니다.
- geometry label은 `r`, `R`, `t`, `n`, `α`와 아래첨자 형식으로 정리되었습니다.

아직 다음 단계:

- 실제 Abaqus viewport 수준의 완전한 mesh renderer는 아닙니다.
- 현재 mesh preview는 GUI 값 기반 안내용이며, 최종 연구 mesh 품질 판정은 Abaqus `.inp/.odb`와 backend 로그가 기준입니다.
- `CPRESS`, `COPEN`, `CSLIP` 같은 contact output은 아직 ODB에서 missing으로 나옵니다.

## 6. 보광이가 backend에서 확인할 부분

1. GUI에서 넘어오는 `input_data.json`의 mesh/analysis key를 유지하면서 full cable 모델 쪽으로 연결.
2. reduced smoke에서 끈 contact pair를 연구용 모델에서는 다시 켜기.
3. armour/filler/contact surface가 비어 있지 않은지 `abaqus_mesh_manifest.json`에 명확히 기록.
4. ODB에 `S`뿐 아니라 `CPRESS`, `COPEN`, `CSLIP1`, `CSLIP2`, `CSHEAR1`, `CSHEAR2`가 나오도록 output request 정리.
5. full cable model에서 pressure step과 bending step이 모두 수렴하는 조건 찾기.

## 7. 지호가 다음에 할 목표

1. GUI에서 mesh/analysis 변수 이름을 교수님 피드백 기준으로 더 짧고 직관적으로 다듬기.
2. GUI mesh preview는 "실제 Abaqus mesh"가 아니라 "설정값 이해용 preview"라는 점을 보고자료에 명확히 표시.
3. 보광이가 full cable 수렴 모델을 주면, 해당 `input_data.json`을 GUI preset 또는 import 기능으로 불러와 같은 변수명으로 재현되는지 확인.
4. 결과 보고자료에는 reduced smoke 성공과 final research model 성공을 분리해서 작성.

## 8. Git 상태

이 검증이 반영된 최신 커밋:

```text
d38d659 Stabilize Abaqus bridge endpoint sweep
```

보광이가 GitHub 기준으로 볼 경우:

```text
git pull
git log --oneline -5
```

