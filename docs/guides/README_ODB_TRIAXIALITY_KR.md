# ODB 노드별 응력삼축도 일괄 추출 (Abaqus 2019 / 2026)

## 현재 상태

실행 가능한 도구와 두 버전용 실행 파일이 있습니다. 작은 합성 ODB에서 Abaqus 2019 및 2026 CAE의 실제 XY 추출/엑셀 저장을 검증했습니다. 사용자 ODB의 실제 응력 결과는 아직 추출하지 않았습니다. SF/DF/FF/SW의 노드 번호, Instance 이름, GUI Position 확인이 남아 있습니다.

## 파일

- `code/odb_triaxiality_config.json`: 사용자 설정. 보통 이 파일만 수정합니다.
- `code/run_odb_triaxiality_2019.bat`: 2019용 더블클릭 실행.
- `code/run_odb_triaxiality_2026.bat`: 2026용 더블클릭 실행.
- `code/odb_triaxiality_2019.py`, `code/odb_triaxiality_2026.py`: 버전별 CAE 진입점.
- `code/odb_triaxiality_batch.py`: 두 버전이 공유하는 본체. 같은 폴더에 두세요.
- `code/check_odb_triaxiality.py`: 일반 검사 및 작은 합성 ODB 생성/검증 도구.

Excel 설치, pandas, openpyxl 설치는 실행에 필요하지 않습니다. XLSX는 Python 표준 라이브러리로 작성합니다. BAT의 기본 Abaqus 경로는 이 PC에서 확인했으며, 다른 PC에서는 BAT의 `ABAQUS_CMD`를 수정하거나 해당 명령을 PATH에 등록하세요.

## 1. 노드 설정

이 PC에는 대상 경로가 채워진 `code/odb_triaxiality_config.json`이 이미 있습니다. 로컬 경로/노드 설정은 Git에 커밋하지 않습니다. 다른 PC에서 처음 사용할 때는 `code/odb_triaxiality_config.example.json`을 같은 폴더의 `odb_triaxiality_config.json`으로 복사하고 ODB 경로와 노드를 입력하세요.

설정 파일의 `node_rules`에서 각 유형의 IP/OP를 입력하세요. 아래 번호/이름은 **작성 형식 예시일 뿐 실제 모델 값이 아닙니다**.

```json
"SF": {
  "IP": {"instance": "PIPE-1", "node": 123},
  "OP": {"instance": "PIPE-1", "node": 456}
}
```

DF/FF/SW도 같은 방식입니다. IP와 OP의 Instance가 달라도 됩니다. Instance 이름의 대소문자는 ODB와 일치시켜 주세요. `null`과 빈 Instance 이름은 미설정 상태입니다. 설정되지 않은 유형은 건너뛰고 목록/오류 기록에 남깁니다. 다른 유형의 노드로 대체하지 않습니다.

파일명의 확장자를 뺀 뒤 밑줄로 나눈 항목에서 SF/DF/FF/SW를 정확하게 찾습니다. 숫자와 접두사는 자유롭게 바뀌어도 됩니다.

- `D15_t15_lD05_SW_dt08_Riks.odb` -> SW
- `D20_t20_lD2_DF_dt04_Riks.odb` -> DF
- `SFF`처럼 일부 글자만 일치하는 이름, 구분이 없거나 두 번 이상 나오는 이름은 오류 목록에 기록합니다.

기본 대상 폴더는 `D:/LYG/260922 SG Buckling Cases/D15_t15_odb`입니다. 현재 직접 확인한 파일은 30개(SF 6 / DF 6 / FF 9 / SW 9)입니다. 기본은 이 폴더 바로 아래만 읽으며 `recursive: true`이면 하위 폴더도 탐색합니다.

## 2. 추출 기준 확인

현재 제공하는 방식은 `position: "NODAL"`, 즉 **Unique Nodal**입니다. Abaqus CAE의 `session.xyDataListFromField`로 S의 Pressure/Mises를 각각 읽습니다. 노드 평균화를 켜고 임계값 100%, 표시 여부와 무관하게 전체 요소를 대상으로 설정합니다. 추가 수작업 평균은 수행하지 않습니다. 원본 응력은 INTEGRATION_POINT에 저장된 S를 사용합니다.

사용자의 GUI가 Element Nodal 등 다른 Position이면 이 설정 그대로 연구용 결과를 비교하지 마세요. 해당 GUI 설정을 먼저 알려주시면 맞춰 수정할 수 있습니다. 현재 사용자 GUI와 수치 일치 여부는 미확인입니다. 한 노드에서 여러 곡선/단면점이 반환되면 첫 곡선을 임의로 택하지 않고 오류로 기록합니다. 필요하면 IP/OP 설정에 Abaqus의 `section_points` 매핑을 추가할 수 있습니다.

- 식: `응력삼축도 = -Pressure / Mises` (무차원).
- Pressure/Mises와 IP/OP의 샘플 수 및 X가 일치하는지 검사합니다. 자동 보간이나 0 채우기는 하지 않습니다.
- Mises가 0이면 삼축도는 빈칸, 상태는 `ZERO_OR_SMALL_MISES`입니다. 필요 시 `mises_zero_tolerance`를 모델 응력 단위에 맞게 조정할 수 있습니다. 기본값 0은 정확히 0일 때만 제외합니다.
- 비정상 수치도 빈칸과 상태로 기록합니다. 유한한 응력 원본은 보존합니다.
- `XY_X`는 Abaqus가 반환한 X를 그대로 저장합니다. **Riks에서 물리적 시간으로 해석하지 마세요.**
- `Sample`은 Step별 XY 데이터의 0 기반 순번입니다. ODB Frame 번호로 가장하지 않습니다. S가 없는 프레임은 Abaqus XY 추출 방식에 따릅니다.
- 기본 `steps: null`은 모든 Step입니다. 예를 들어 `steps: ["Pressure"]`이면 해당 Step만 처리합니다.
- `max_frames_per_step: null`은 모든 활성 프레임입니다. 작은 시험에는 양의 정수를 설정할 수 있습니다. 값이 N이면 프레임 0부터 N-1까지를 요청합니다.

## 3. 목록만 먼저 확인

저장소 루트에서 일반 Python으로 실행합니다. ODB 자체는 열지 않습니다.

```powershell
python code/odb_triaxiality_batch.py --plan
```

생성되는 `Inventory.xlsx`는 파일명 분류/노드 설정 상태 목록이며 **응력 추출 결과가 아닙니다**.

## 4. 실제 실행

설정 후 해당 버전의 BAT를 더블클릭하거나, 저장소 루트에서 실행합니다.

```powershell
& 'C:\SIMULIA\Commands\abq2019.bat' cae noGUI=code/odb_triaxiality_2019.py
& 'C:\Program Files\SIMULIA\Commands\abq2026.bat' cae noGUI=code/odb_triaxiality_2026.py
```

두 명령은 각각 사용할 때의 예시입니다. 같은 폴더를 두 버전에서 연속으로 처리할 필요는 없습니다. 다른 설정이나 한 파일 시험은 다음처럼 실행합니다.

```powershell
& 'C:\SIMULIA\Commands\abq2019.bat' cae noGUI=code/odb_triaxiality_2019.py -- --only D15_t15_lD05_SW_dt08_Riks.odb
& 'C:\Program Files\SIMULIA\Commands\abq2026.bat' cae noGUI=code/odb_triaxiality_2026.py -- --config C:/path/to/config.json --limit 1
```

파일은 한 번에 하나씩 읽고, 완료되는 즉시 해당 XLSX를 저장합니다. 개별 ODB 실패 후에도 다음 파일을 계속 처리합니다. 기본 출력은 저장소의 `outputs/odb_triaxiality/실행일시/`입니다. 상대 경로는 설정 파일 위치 기준이며 `output_folder`를 절대경로로 바꿀 수도 있습니다. 실행마다 새 폴더를 만들어 기존 결과를 덮어쓰지 않습니다.

## 5. 결과와 진행상황

각 ODB의 Excel 파일에는 다음 시트가 있습니다.

- `Combined`: 같은 X에 대한 IP·OP Pressure/Mises/삼축도/상태 비교.
- `TP_IP`, `TP_OP`: 각각의 Step, Sample, XY_X, Pressure, Mises, 삼축도, 상태.
- `Metadata`: 원본 경로, 적용한 설정, 산식, Position과 평균화 정보, 실행 버전 및 해석상 주의점.

같은 실행 폴더의 `Batch_summary.xlsx`는 전체 파일별 성공/실패 목록입니다. `progress.log`는 처리 시작/Step/노드/저장/오류를 계속 기록합니다. `batch_report.json`도 파일마다 갱신됩니다. 큰 ODB의 한 번의 XY 추출 호출 안에서는 프레임별 진행률을 알 수 없으므로 그동안 로그가 멈춰 있을 수 있습니다.

Abaqus의 Python 출력은 버전에 따라 콘솔 대신 replay 파일로 갈 수 있습니다. 실행 폴더의 `progress.log`와 `batch_report.json`을 확인하세요. 이 PC의 2019 런처는 CAE 내부 오류 때도 OS 종료코드 0을 반환하는 경우가 있으므로 성공 판정에는 결과 목록의 `OK`를 사용하세요.

noGUI가 끝나면 CAE 세션의 XY 객체는 사라집니다. 지속되는 결과는 XLSX입니다. GUI에서 실제 `TP_IP`/`TP_OP` 객체도 남기려면 원본 ODB를 그 세션에서 닫은 뒤 Python 콘솔에서 다음처럼 본체를 호출할 수 있습니다.

```python
import sys
sys.path.insert(0, r'C:\Users\user\Documents\SCLAS-cable-analysis\code')
import odb_triaxiality_batch as triax
triax.main(target='2019', argv=['--only', 'D15_t15_lD05_SW_dt08_Riks.odb', '--keep-xy'])
```

2026에서는 target을 `2026`으로 바꿉니다. 한 Step이면 `TP_IP`/`TP_OP`, 여러 Step이면 `TP_IP__Step이름`/`TP_OP__Step이름`으로 생성합니다. 기존 이름은 덮어쓰지 않습니다. 정의되지 않는 삼축도 행은 XY 객체에서 제외하며 Excel에는 빈칸과 상태로 남습니다. 제외된 구간의 앞뒤 유효값이 그래프상 연결될 수 있으므로 해당 구간 판단은 Excel의 상태 열을 사용하세요. `--keep-xy`는 한 ODB만 선택했을 때 사용할 수 있습니다.

## 원본과 버전 호환

원본은 readOnly=True로 열고 저장하거나 업그레이드하지 않습니다. 이미 현재 CAE 세션에서 연 ODB는 건너뛰며 사용자가 연 파일을 닫지 않습니다. BAT/noGUI는 별도 CAE 세션에서 실행됩니다.

**스크립트의 두 버전 호환성과 ODB 파일 포맷 호환성은 별개입니다.** 더 최신 버전에서 만든 ODB는 2019에서 열리지 않을 수 있고, 구형 ODB는 2026에서 업그레이드를 요구할 수 있습니다. 그런 경우 오류로 기록합니다. 자동 복사/업그레이드는 하지 않습니다. 각 버전에서 열 수 있는 ODB 폴더를 설정해 주세요.

## 검증 기록 (2026-11-20)

- 일반 Python 3.12 및 Abaqus 2019 Python 2.7 / 2026 Python 3.10에서 5개 기본 검사 통과.
- 각각의 버전에서 직접 생성한 2개 C3D8R 요소, 2 Step, 각 3프레임의 작은 합성 ODB로 CAE 추출/엑셀 저장 검증.
- 독립 노드에서 IP=1/3, OP=4/3; Mises=0인 초기행은 빈칸.
- 공유 노드에서는 서로 다른 두 요소의 Pressure/Mises에 대한 평균 결과로 IP=5/6, OP=4/3 확인.
- 독립 라이브러리 openpyxl로 생성 XLSX를 다시 열어 시트/수치/빈칸 검사. 실행 도구 자체에는 openpyxl이 필요하지 않음.
- 추출 전후 합성 ODB의 SHA256 동일.
- 실제 사용자 30개 ODB는 목록 분류만 확인. 실데이터 추출과 사용자 GUI 대조는 노드/Instance/Position 확인 후 수행해야 함.
- 프로젝트 전체 `scripts/run_self_check.bat`는 기존 Python 2 print 구문(`code/abaqus_runner.py:1810`, `code/abaqus_runner_V89.py:1598`) 때문에 compilation 단계 실패. 해당 기존 파일들은 이번 작업에서 수정하지 않음.

일반 검사:

```powershell
python code/check_odb_triaxiality.py
```

새 합성 ODB 생성은 해당 Abaqus Python에서 `code/check_odb_triaxiality.py --fixture 새폴더`를 실행합니다. 그 폴더의 `config.json`으로 버전별 CAE 진입점을 실행한 뒤, 일반 Python에서 `code/check_odb_triaxiality.py --verify 폴더`로 기본 정답/빈칸/ODB 해시를 확인할 수 있습니다. 합성 파일이나 결과물은 Git에 넣지 않습니다.

공식 API 참고:

- [XYData / xyDataListFromField](https://docs.software.vt.edu/abaqusv2025/English/SIMACAEKERRefMap/simaker-c-xydatapyc.htm)
- [OdbData / activeFrames](https://docs.software.vt.edu/abaqusv2025/English/SIMACAEKERRefMap/simaker-c-odbdatapyc.htm)
- [BasicOptions](https://docs.software.vt.edu/abaqusv2025/English/SIMACAEKERRefMap/simaker-c-basicoptionspyc.htm)
