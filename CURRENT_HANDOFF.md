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
b2c17a1 Document Windows HELIX GUI verification
```

## Current Focus

Continue HELIX GUI refinement while preparing the Abaqus backend to move from a
placeholder/scaffold runner toward a literature-informed nonlinear bending
workflow.

Windows home-computer GUI verification has now passed for the current
`11.5-resizable-panels` baseline.

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
- Windows GUI startup was verified through `run_sclas.bat` using the existing
  Windows-ready `.venv`.
- Design, Mesh, and Analysis pages were screenshot-checked at 1366x768.
- The three main pages expose horizontal splitters and vertical scroll areas;
  no blocking text/control clipping was observed in the captured views.
- Mesh preview generation was exercised and produced 119 preview items with
  readiness state changing to preview ready.
- The backend contract is established through `input_data.json`,
  `result_data.csv`, and optional `result_summary.json`.
- `code/abaqus_runner.py` placeholder summaries now include
  `result_contract`, `backend_readiness`, and
  `hysteresis_loss_kj_per_m_proxy` so `code/sclas_self_check.py` passes.
- Lab PC Abaqus/CAE 2019 was reached through ZeroTier/RDP. Its noGUI Python is
  Python 2-era, so `code/abaqus_runner.py` has been converted away from Python
  3-only syntax such as type annotations, f-strings, `pathlib`, and
  `datetime.isoformat(timespec=...)`.
- Phase 2 contact/friction scaffolding has started: `code/abaqus_runner.py`
  now creates an Abaqus `ContactProperty` named `SCLAS_RegularizedContact`
  with normal/tangential behavior parameters from the GUI payload. Real
  surface-to-surface interaction pairs are still pending.
- The Abaqus mesh scaffold now also creates stable contact region placeholders:
  solid parts expose `ContactFaces` / `ContactSurface` at part level plus
  assembly-level `*_ContactFaces` / `*_ContactSurface`; B31 armour parts expose
  `ContactEdges` plus assembly-level `*_ContactEdges`. The manifest records
  these under `contact_region_scaffold` and keeps declared interface bindings
  under `contact_binding_scaffold` until real interactions are implemented.
- The Abaqus runner now attempts an executable Standard general-contact
  interaction named `SCLAS_GeneralContact`, assigning
  `SCLAS_RegularizedContact` at global/self scope when Abaqus/CAE supports the
  API. This is still a scaffold; explicit pair-level interfaces for bedding,
  inner sheath, and armour layers are pending until those layer surfaces are
  represented directly.
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

Latest Windows verification performed with:

```bat
python -m py_compile code\sclas_remote_gui.py code\SCLAS_test\sclas_remote_gui.py code\abaqus_runner.py code\SCLAS_test\abaqus_runner.py
python code\sclas_self_check.py
```

Result: both passed using the Windows-ready virtual environment.

After Abaqus-runner edits, also re-run an Abaqus noGUI smoke test on the lab PC:

```bat
abaqus cae noGUI=abaqus_runner.py -- input_data.json
```

Expected minimum outputs remain `result_data.csv`, `result_summary.json`, and
`abaqus_mesh_manifest.json`. If the Abaqus mesh scaffold succeeds, expect
`sclas_mesh_model.cae` and a generated `.inp` file as well.

For the contact scaffold check, open the generated `.cae` and verify that
`Interaction Properties` contains `SCLAS_RegularizedContact`. The manifest
should also include `contact_property_scaffold`, `contact_region_scaffold`, and
`contact_binding_scaffold`. In the CAE model tree, check the generated part and
assembly Sets/Surfaces for `ContactFaces`, `ContactSurface`, and
`ContactEdges`. If the general contact API succeeds, the manifest should also
include `contact_interaction_scaffold` with `SCLAS_GeneralContact`, and the CAE
model tree should show this under Interactions.

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

1. Re-run the lab Abaqus/CAE noGUI smoke test and verify the new
   `contact_interaction_scaffold` entry.
2. Open the generated `.cae` and verify `SCLAS_GeneralContact` appears under
   Interactions.
3. Bind explicit surface-to-surface or beam-to-surface contact pairs to
   `SCLAS_RegularizedContact`.
4. Preserve the GUI contract:
   - `input_data.json` as backend input
   - `result_data.csv` with `curvature_1_per_m,moment_kn_m`
   - `result_summary.json` for optional metrics
5. Add periodic boundary conditions and cyclic bending boundary conditions.
6. Add Abaqus job submission/status handling and ODB extraction into
   `result_data.csv`.
7. After each meaningful task, update this file, commit, and push.

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
