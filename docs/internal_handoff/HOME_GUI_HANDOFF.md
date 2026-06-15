# Home GUI Handoff

> Current handoff source: read `AGENTS.md` and `CURRENT_HANDOFF.md` first.
> This file is kept as an extra Windows/home-computer quick reference.

This document is for continuing SCLAS GUI work on the home Windows desktop with
Codex, Visual Studio Code, Python, and eventually Abaqus.

## Repository

GitHub repository:

```text
https://github.com/jhpark391-afk/SCLAS-cable-analysis
```

Latest known handoff commit:

```text
bdafbfb Add resizable HELIX GUI panels
```

## First setup on the home computer

If the repository is not cloned yet:

```bat
git clone https://github.com/jhpark391-afk/SCLAS-cable-analysis.git
cd SCLAS-cable-analysis
```

If the repository already exists:

```bat
cd SCLAS-cable-analysis
git pull
```

Install or refresh Python dependencies:

```bat
setup_windows.bat
```

Run the GUI:

```bat
run_sclas.bat
```

If using Visual Studio Code, open this folder as the workspace:

```text
SCLAS-cable-analysis
```

## Main files for GUI work

Edit these first:

```text
code/sclas_remote_gui.py
```

Keep these synced after GUI edits:

```text
code/SCLAS_test/sclas_remote_gui.py
code/sclas_remote_gui_final_code.txt
```

The current GUI direction is:

```text
Codex / Apple dark UI
left sidebar navigation
clean graphite palette
English labels
engineering-program feel
no bottom clipping on laptop screens
```

Current GUI version string:

```text
11.5-resizable-panels
```

## Files for backend work

The Abaqus bridge starts here:

```text
code/abaqus_runner.py
```

The GUI creates job folders containing:

```text
input_data.json
BACKEND_CONTRACT.md
abaqus_runner.py
```

For Abaqus execution inside a job folder:

```bat
abaqus cae noGUI=abaqus_runner.py -- input_data.json
```

Expected GUI-readable backend result:

```csv
curvature_1_per_m,moment_kn_m
```

## Do not commit these

Generated or local-only files should stay out of Git:

```text
jobs/
settings.json
.DS_Store
90_env/
venv/
.venv/
*.odb
*.cae
*.sim
```

## Verification commands

After editing GUI code:

```bat
python -m py_compile code\sclas_remote_gui.py code\SCLAS_test\sclas_remote_gui.py
run_sclas.bat
```

After editing backend runner:

```bat
python -m py_compile code\abaqus_runner.py code\SCLAS_test\abaqus_runner.py
```

## Home Codex prompt

Copy this prompt into Codex on the home computer:

```text
이 저장소는 HELIX / SCLAS submarine cable analysis GUI/ABAQUS bridge 프로젝트야.

먼저 git pull, git status를 실행하고 AGENTS.md와 CURRENT_HANDOFF.md를 읽어줘.
주요 GUI 파일은 code/sclas_remote_gui.py야.
현재 UI 방향은 Codex/Apple 느낌의 왼쪽 사이드바 구조이고,
영어 라벨을 유지하면서 깔끔하고 세련된 엔지니어링 프로그램처럼 다듬는 거야.

수정할 때는:
1. code/sclas_remote_gui.py를 먼저 수정
2. 같은 내용을 code/SCLAS_test/sclas_remote_gui.py와 code/sclas_remote_gui_final_code.txt에 동기화
3. python -m py_compile로 문법 체크
4. run_self_check.bat 또는 run_sclas.bat로 확인
5. 필요하면 git commit 후 push

주의:
- jobs/, settings.json, venv류, Abaqus 결과 파일은 커밋하지 마.
- GUI 아래가 잘리면 창 높이 자동 맞춤, 스크롤 영역, 고정 minimum height부터 확인해줘.
- 백엔드 연동은 code/abaqus_runner.py에서 시작돼 있고,
  Abaqus에서는 abaqus cae noGUI=abaqus_runner.py -- input_data.json 형식으로 실행할 예정이야.

우선 현재 GUI 구조와 스타일을 읽고, Windows에서 화면/스크롤/splitter가 정상인지 확인한 뒤 이어서 도와줘.
```

## Suggested next GUI tasks

1. Refine sidebar spacing and selected state.
2. Make cards more compact on smaller laptop screens.
3. Add subtle hover/pressed states to important buttons.
4. Improve Mesh preview framing and empty-state appearance.
5. Polish Analysis page layout so logs, controls, and plot all remain visible.
6. Add a simple theme constants section if the stylesheet gets too large.
