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
2. Open this folder as a Python project.
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

or run:

```bat
run_sclas.bat
```

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
```

## Common Windows issues

- If `PyQt5` fails to install, check that the selected Python version is a normal
  64-bit CPython install.
- If the GUI opens but the 3D view is blank, update the graphics driver and test
  with the `FAST GUI preview` mode first.
- If `abaqus` is not recognized, add the Abaqus command folder to PATH or use the
  full path to the Abaqus command in the GUI local command field.
- Keep `jobs/SCLAS_jobs/job_*` folders out of Git unless you intentionally want
  to share a specific run package.
