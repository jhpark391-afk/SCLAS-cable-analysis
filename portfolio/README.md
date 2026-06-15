# HELIX / SCLAS Portfolio Overview

이 폴더는 **SCLAS 해저 케이블 구조 해석 자동화 및 GUI 파이프라인 프로젝트**를 포트폴리오 형태로 상세히 어필하기 위해 작성된 산출물 공간입니다. 

단순한 개인 토이 프로젝트가 아니라, 실제 산업 현장의 비선형 접촉 해석 공수를 효율화하고 표준화하기 위한 **상용화 직전 단계의 제품급(Production-grade) 분석 도구**임을 보여줍니다.

---

## 📂 포트폴리오 주요 산출물
* **`SCLAS_Portfolio_Overview_KR.pptx`**: 한국어 기술 포트폴리오 및 아키텍처 요약 PPTX 슬라이드 (학계 문헌 대비 정밀도, 백엔드 연동 흐름, QA 자가 진단 체계 포함).
* **`SCLAS_Portfolio_Overview_KR_contact_sheet.png`**: 전체 슬라이드 흐름을 한눈에 볼 수 있도록 구성한 슬라이드 미리보기 밀착화(Contact Sheet) 이미지.

---

## 🏆 포트폴리오 핵심 어필 포인트 (Value Propositions)

### 1. 개발자로서의 소프트웨어 품질 관리 (QA) 능력 증명
* **자가 검증 테스트 수트 구축**: 18가지 검증 항목(Python 컴파일 체크, 파일 싱크, mock ODB 추출 테스트 등)을 내장한 `sclas_self_check.py`를 구현하여, 협업이나 배포 시 코드의 완결성을 자동으로 증명하는 빌드 체계를 갖추었습니다.

### 2. 현업 설계 리드타임 혁신
* **90% 리드타임 단축**: 수일씩 걸리던 아바쿠스 기하 설계 및 비선형 접촉 수동 세팅 과정을 GUI 원클릭으로 주입하고 비동기로 결과를 돌려받는 파이프라인을 구축하여, 기업의 엔지니어링 공수를 획기적으로 낮췄습니다.

### 3. 문헌 대비 캘리브레이션 튜닝 시스템
* **물리 신뢰성 실시간 검증**: [sclas_calibration_report.py](file:///Users/parkjiho/Desktop/코덱스저장소/01_SCLAS_케이블해석/code/sclas_calibration_report.py) 모듈을 통해 해석 완료 데이터와 학술적 캘리브레이션 타겟(탄성 강성, 슬립 강성, 에너지 소실 등)을 자동 비교하고, 이를 GUI 요약창에 렌더링해 줌으로써 해석 품질의 안정성을 보증합니다.

---

## 🎨 Preview (Slide Contact Sheet)
![SCLAS portfolio contact sheet](SCLAS_Portfolio_Overview_KR_contact_sheet.png)
