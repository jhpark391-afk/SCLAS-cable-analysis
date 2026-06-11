# CURRENT_HANDOFF

Last updated: 2026-06-11

## Repository

GitHub:

```text
https://github.com/jhpark391-afk/SCLAS-cable-analysis
```

Current shared branch:

```text
main
```

Latest completed GUI baseline commit:

```text
bdafbfb Add resizable HELIX GUI panels
```

## Current Focus

Continue HELIX GUI refinement while preparing the Abaqus backend to move from a
placeholder/scaffold runner toward a literature-informed nonlinear bending
workflow.

## Current Working State

- The GUI runs through `code/sclas_remote_gui.py`.
- HELIX branding and team logo assets are integrated.
- UI language toggle exists for English/Korean labels.
- Design, Mesh, and Analysis pages use sidebar navigation.
- Each page has scroll-safe panel wrappers.
- Design, Mesh, and Analysis pages now use horizontal resizable splitters.
- Analysis page has collapsible sections.
- FAST GUI preview produces a moment-curvature hysteresis loop.
- CSV comparison, PNG export, result summary, and recent job loading exist.
- Mesh preview exists and exports mesh/backend request settings.
- The backend contract is established through `input_data.json`,
  `result_data.csv`, and optional `result_summary.json`.
- `code/abaqus_runner.py` is still not a complete research-grade Abaqus solver.

## Important Files

```text
code/sclas_remote_gui.py
code/SCLAS_test/sclas_remote_gui.py
code/sclas_remote_gui_final_code.txt
code/abaqus_runner.py
code/SCLAS_test/abaqus_runner.py
README_SCLAS_WORKFLOW.md
README_LITERATURE_NOTES.md
README_WINDOWS_VISUAL_STUDIO.md
docs/HELIX_BACKEND_HANDOFF_BOGWANG_KR.md
screenshots/gui/
```

## GUI Sync Rule

If `code/sclas_remote_gui.py` is edited, copy the same file to:

```text
code/SCLAS_test/sclas_remote_gui.py
code/sclas_remote_gui_final_code.txt
```

Then run the verification commands below.

## Required Verification

On macOS:

```bash
../90_env/venv/bin/python -m py_compile code/sclas_remote_gui.py code/SCLAS_test/sclas_remote_gui.py
../90_env/venv/bin/python code/sclas_self_check.py
```

On Windows:

```bat
run_self_check.bat
```

Or manually:

```bat
python -m py_compile code\sclas_remote_gui.py code\SCLAS_test\sclas_remote_gui.py
python code\sclas_self_check.py
```

## Research Implementation Status

The papers are not fully implemented yet.

Already reflected in the GUI/backend contract:

- bending moment-curvature hysteresis loop
- stick-slip / friction / residual contact pressure inputs
- hydrostatic pressure input
- torsion, tension-bending coupling, compression/bird-caging, pressure-effect
  study scope
- periodic homogenized cell modelling option
- beam + contact surface armour modelling option
- contact regularization parameter
- Abaqus-readable job package structure

Still needed for a paper-level implementation:

1. Real Abaqus contact/friction pair definitions.
2. Periodic boundary conditions.
3. Cyclic bending boundary conditions.
4. Abaqus job submission and status handling.
5. ODB extraction into `result_data.csv`.
6. Calibration of friction and residual contact pressure against reference or
   measured loops.
7. Coupled torsion, tension, compression, and pressure load cases.
8. Local slip, contact pressure, stress, and fatigue-oriented summary metrics.

## Next Recommended Tasks

1. On the home Windows computer, run `git pull` and verify the GUI opens.
2. Check that splitters, scroll panels, and font sizing behave correctly on the
   Windows display.
3. If the GUI breaks on Windows, fix layout/runtime issues first.
4. Start backend work in `code/abaqus_runner.py`.
5. Preserve the GUI contract:
   - `input_data.json` as backend input
   - `result_data.csv` with `curvature_1_per_m,moment_kn_m`
   - `result_summary.json` for optional metrics
6. After each meaningful task, update this file, commit, and push.

## Home Codex Start Prompt

Use this prompt when starting work on the home computer:

```text
This is the HELIX / SCLAS submarine cable analysis repository.

First run git pull and git status. Then read AGENTS.md and CURRENT_HANDOFF.md.
Summarize the current project state, the latest handoff, and the next task.

Before editing, tell me which files you will touch. After editing, run the
project verification commands. If code/sclas_remote_gui.py changes, sync it to
code/SCLAS_test/sclas_remote_gui.py and code/sclas_remote_gui_final_code.txt.

The immediate priority is to verify the GUI on Windows, then continue preparing
code/abaqus_runner.py for real Abaqus contact, periodic boundary conditions,
cyclic bending, job submission, and ODB result extraction.
```
