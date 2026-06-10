# SCLAS 연구/개발 백로그 한국어 요약

이 문서는 보광이가 프로젝트 방향을 빠르게 이해할 수 있도록, 현재 참고한 공개 자료와
개발 우선순위를 한국어로 정리한 것입니다.

## 참고한 공개 자료

### Dai et al. 2025

주제:

- subsea umbilical / power cable의 contact 해석
- contact interface, penalty factor, element refinement가 결과에 민감하게 작용
- Abaqus와 비교 검증

SCLAS에 반영할 점:

- contact-friction 정의가 백엔드 핵심임
- contact parameter sweep이 필요함
- `result_summary.json`에 contact 관련 수렴/민감도 정보를 남겨야 함

### Goyal, Perkins, Lee 2007

주제:

- 낮은 장력과 torsion 상태에서 cable이 loop, hockle, self-contact 상태로 갈 수 있음
- twist energy가 bending/writhe로 변환됨

SCLAS에 반영할 점:

- 현재 GUI의 local bending 해석 이후 torsion/self-contact 위험까지 확장 가능
- bird-caging 또는 low-tension instability 지표를 장기적으로 고려할 수 있음

### Goyal and Perkins 2007

주제:

- 전체 cable을 모두 고정밀 rod model로 풀면 계산 비용이 큼
- high-tension 영역은 단순 catenary, low-tension/local 영역은 rod model로 나누는 hybrid approach 제안

SCLAS에 반영할 점:

- 지금은 local periodic cell 중심으로 개발
- 나중에 전체 cable/global model과 local Abaqus high-fidelity model을 연결하는 방향 가능

### CAE GUI 참고

FEATool 같은 CAE GUI는 보통 다음 흐름을 명확히 보여줍니다.

```text
Geometry -> Mesh/Grid -> Physics/Boundary -> Solve -> Post
```

SCLAS GUI도 현재 다음 구조를 따릅니다.

```text
Design -> Mesh -> Analysis
```

추가로 result summary panel을 넣어, solve 이후 backend 상태와 연구 지표를 바로 볼 수 있게 했습니다.

## 개발 우선순위

1. `result_data.csv` 계약 유지
   - header: `curvature_1_per_m,moment_kn_m`
2. Abaqus mesh scaffold 검증
3. armour/sheath/bedding contact-friction 정의
4. cyclic bending boundary condition 추가
5. ODB에서 moment-curvature 추출
6. `result_summary.json`에 contact pressure, slip, stiffness 지표 저장
7. torsion stiffness 해석 추가
8. tension-bending coupling 해석 추가
9. pressure/compression/bird-caging risk 해석 추가

## 지금 당장 보광이가 보면 좋은 파일

```text
README_BOGWANG_HANDOFF_KR.md
docs/ABAQUS_BACKEND_IMPLEMENTATION_PLAN_KR.md
code/abaqus_runner.py
code/sclas_remote_gui.py
```

영어 문서는 보조 자료로 보면 됩니다.
