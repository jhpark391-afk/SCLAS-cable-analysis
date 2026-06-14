# SCLAS on Windows Visual Studio

## What to copy

Copy or clone this folder:

```text
01_SCLAS_케이블해석/
```

Do not copy the Mac virtual environments under `../90_env`. They cannot run on
Windows. Create a fresh Windows virtual environment instead.

## Visual Studio setup

1. Open Visual Studio.
2. Open `SCLAS-cable-analysis.sln`.
3. Create a new virtual environment at:

```text
01_SCLAS_케이블해석\.venv
```

4. Install dependencies:

```bat
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

5. Set the startup file to:

```text
code\sclas_remote_gui.py
```

The included `SCLAS-cable-analysis.pyproj` already sets this startup file.
You can also run:

```bat
run_sclas.bat
```

To verify the local project contract after edits, run:

```bat
run_self_check.bat
```

For the full repeatable handoff/validation pass, run:

```bat
run_validation_suite.bat
```

This runs self-check, saves the result-intake report, saves the acceptance gate
report, saves the handoff snapshot, regenerates the next Codex prompt, and writes
`validation_suite_report.json` / `validation_suite_report.md` with the current
git branch/head plus dirty, upstream, sync label, and ahead/behind counts.

After copying or pulling a remote Abaqus result folder, run:

```bat
run_result_intake.bat
run_acceptance_gate.bat
```

The intake script checks whether the copied folder has the expected result CSV,
summary, solver logs, ODB evidence, local fields, and contact indicators. The
acceptance gate then gives a research-readiness pass/review/blocked decision for
the latest job.

Before switching computers or handing work to another Codex session, save a
compact project snapshot with:

```bat
run_handoff_snapshot.bat
```

This writes `handoff_snapshot.json` and `handoff_snapshot.md` at the project
root.

To generate the ready-to-paste prompt for the next Codex session, run:

```bat
run_next_prompt.bat
```

This writes `NEXT_CODEX_PROMPT.md` at the project root.

## Backend command on Windows

For placeholder backend testing, use:

```bat
python abaqus_runner.py input_data.json
```

For real Abaqus execution, the GUI local command should usually be:

```bat
abaqus cae noGUI=abaqus_runner.py -- input_data.json
```

Run this command inside each generated job folder. The GUI's
`Run local/shared-folder command` mode already does that.

When `abaqus_runner.py` is executed inside Abaqus/CAE, it converts the GUI mesh
settings into a first-pass Abaqus mesh scaffold:

```text
abaqus_mesh_manifest.json
sclas_mesh_model.cae
<job_name>_mesh.inp
```

The scaffold uses the Mesh tab's element type and seed counts. Armour wires are
represented as B31 helical beam paths at this stage; contact pairs, bending
boundary conditions, and ODB-based result extraction are the next backend tasks.

## Expected job outputs

Each backend run must create:

```text
result_data.csv
```

with this exact header:

```csv
curvature_1_per_m,moment_kn_m
```

Optional:

```text
result_summary.json
abaqus_mesh_manifest.json
sclas_mesh_model.cae
<job_name>_mesh.inp
```

## Common Windows issues

- If `PyQt5` fails to install, check that the selected Python version is a normal
  64-bit CPython install.
- If `setup_windows.bat` says the existing `.venv` Python cannot start, rename
  or delete `.venv`, install or select a valid Python 3 interpreter, then run
  `setup_windows.bat` again.
- If the GUI opens but the 3D view is blank, update the graphics driver and test
  with the `FAST GUI preview` mode first.
- If `abaqus` is not recognized, add the Abaqus command folder to PATH or use the
  full path to the Abaqus command in the GUI local command field.
- Keep `jobs/SCLAS_jobs/job_*` folders out of Git unless you intentionally want
  to share a specific run package.
