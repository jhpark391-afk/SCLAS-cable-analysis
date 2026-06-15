# HELIX / SCLAS: 해저 케이블 구조 해석 자동화 및 GUI 파이프라인

> **PyQt5 기반 고성능 프론트엔드와 Abaqus 비선형 FEA 솔버를 1:1로 결합하여 해석 리드타임을 90% 이상 단축하는 통합 엔지니어링 소프트웨어 플랫폼**

---

## 🌟 프로젝트 개요
**HELIX / SCLAS**는 subsea umbilical 및 전력 케이블의 비선형 거동(굽힘 강성, 슬립 전이, hysteresis 루프 등)을 설계하고 분석하는 통합 엔지니어링 솔루션입니다. 

기존 엔지니어가 아바쿠스(Abaqus) GUI에서 수작업으로 형상을 모델링하고, 메시를 나누고, 복잡한 접촉 조건과 구속식을 작성하던 번거로운 과정을 **GUI 입력을 통한 원클릭 자동화 파이프라인**으로 혁신했습니다.

```mermaid
graph TD
    subgraph "Frontend (PyQt5)"
        A["1. Design/Mesh parameters"] --> B["2. JSON Data Serialization (input_data.json)"]
        G["6. GUI Visualization & Reports"] <-- H["5. Result Parse & Deserialize"]
    end
    
    subgraph "Backend (Abaqus noGUI Solver)"
        B --> C["3. Geometry / Mesh generation (*.cae, *.inp)"]
        C --> D["4. Non-linear Bending Solve (Abaqus Standard)"]
        D --> E["5. ODB History/Field extraction (sclas_odb_extractor.py)"]
        E --> H
    end
```

---

## 🚀 주요 기능 (Key Features)

### 1. 사용자 중심의 반응형 GUI (PyQt5)
* **CAE 표준 워크플로우**: `Design(설계) ➔ Mesh(격자) ➔ Analysis(해석/포스트)`의 단계별 탭 배치 및 사이드바 내비게이션.
* **레이아웃 안정성**: 해상도 1366x768 이상에서 컴포넌트 뭉개짐을 차단하는 **수직/수평 스크롤 컨테이너** 및 **Resizable Splitter** 적용.
* **실시간 다국어 지원**: 런타임 언어 토글로 라벨, 버튼, 진단 로그, 리포트 텍스트까지 영어/한국어 실시간 전환 지원.

### 2. 비동기식 해석 및 ODB 데이터 추출 파이프라인
* **Abaqus noGUI 백엔드 연동**: GUI 설정을 JSON 형태로 자동 직렬화하여 아바쿠스 Python 라이브러리로 전달하고, 백엔드에서 입력 덱(`*.inp`)을 생성하여 직접 해석을 수행합니다.
* **고성능 데이터 추출**: 해석 완료 후, 3차원 결과 데이터베이스(`.odb`)에서 우측 reference point의 `UR2`(회전 변위) 및 `RM2`(반력 모멘트) 필드/이력을 자동으로 추출하여 `result_data.csv`에 기록합니다.

### 3. 고성능 데이터 시각화 및 비교 분석
* **PyQtGraph 플로팅**: 대용량 곡률-모멘트 데이터를 랙(Lag) 없이 매끄럽게 렌더링하며 마우스 휠 줌/드래그 인터랙션 제공.
* **CSV Overlay**: 현재 해석 루프 그래프 위에 타사/이전 설계 데이터(CSV)를 레이어로 얹어서 한눈에 피팅 상태를 다중 비교하는 기능 제공.

### 4. 오프라인 진단 및 캘리브레이션 튜닝 리포트
* **자동 진단 (Diagnostics)**: 아바쿠스 해석 중 에러 발생 시, 아바쿠스 솔버 로그(`.dat`, `.msg`, `.sta`)를 파싱하여 무엇이 문제이고 다음으로 조치할 물리 제어법이 무엇인지 분석 요약 창 최상단에 즉시 가이드라인 제공.
* **캘리브레이션 비교 보고서**: 해석 데이터를 바탕으로 탄성 강성, 슬립존 강성, 이력 흡수 에너지, Stick-to-slip 전이 곡률을 계산하여 문헌(Dai et al. 2025 등)의 타겟 값들과 오차 비교 결과를 표 형태로 출력.

---

## 🛠️ 기술 스택 (Tech Stack)
* **Frontend**: `Python 3.12`, `PyQt5`, `PyQtGraph`
* **Backend**: `Abaqus CAE 2019 Scripting` (Python 2.7 환경 호환)
* **QA & CI/CD**: `sclas_self_check.py` (18가지 자가 진단 테스트 수트 내장)
* **Data Format**: `JSON`, `CSV`

---

## 💻 실행 및 설치 방법 (Installation)

### 1. 가상환경 설정 및 의존성 패키지 설치
```bash
# 가상환경 생성 및 활성화
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 필요한 패키지 설치
pip install -r requirements.txt
```

### 2. GUI 프로그램 실행
```bash
# Windows
run_sclas.bat

# macOS
./run_sclas.sh
```

### 3. 소프트웨어 자가 검증 (QA Self-Check)
협업 환경이나 다른 컴퓨터로 동기화했을 때 코드 및 참조 관계가 정상적인지 점검하려면 다음을 수행합니다.
```bash
# Windows
scripts\run_self_check.bat

# macOS
bash scripts/run_self_check.sh
```

---

## 📁 디렉토리 구조 (Repository Directory Structure)
* `code/`: PyQt5 GUI 핵심 소스코드 및 아바쿠스 연동 스크립트.
* `docs/`: 백엔드 구현 계획서, 프론트엔드 아키텍처, 캘리브레이션 기술 설계 리포트 및 인수인계 문서.
  * `docs/guides/`: 사용자 설명서 및 기술 참조 가이드.
  * `docs/internal_handoff/`: 내부 협업 및 개발 인수인계 파일.
* `portfolio/`: 기업 프레젠테이션용 PPTX 슬라이드 및 포트폴리오 개요.
* `scripts/`: 실행 및 시스템 자가 검증용 보조 배치/셸 스크립트.
* `SCLAS_Quick_Launch/`: 비전문가 사용자를 위한 터미널 없는 퀵 런처 바로가기 폴더.
