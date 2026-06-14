# HELIX / SCLAS Workflow

## Research goal

HELIX is being developed as an integrated framework for evaluating local
behavior of submarine power cables.

HELIX = **Helical Element Localised Interaction eXamination**

The primary workflow is:

```text
design variables -> cable section/helix geometry -> Abaqus automation -> local behavior metrics -> GUI visualization
```

The first GUI output is the bending moment-curvature hysteresis loop, but the
backend contract already carries a wider research scope:

- bending stick-slip and stiffness degradation
- torsion stiffness
- tension-bending coupling
- compression/bird-caging risk
- hydrostatic pressure effect

See `README_LITERATURE_NOTES.md` for how the Chang and Chen 2019 and Menard
and Cartraud 2023 papers map into the current GUI/backend contract.
See `docs/SCLAS_RESEARCH_BACKLOG.md` for the current public-reference scan and
implementation backlog.
See `docs/ABAQUS_BACKEND_IMPLEMENTATION_PLAN.md` for the staged Abaqus contact,
cyclic bending, and ODB extraction plan.
See `docs/HELIX_FINAL_COMPLETION_ROADMAP.md` for the final completion split
between Mac/home Codex work and remote Windows/Abaqus work.
See `docs/HELIX_BACKEND_HANDOFF_BOGWANG_KR.md` for the current Korean handoff
contract for the Abaqus backend owner.

## Main entry point

Run the GUI on macOS from:

```bash
./run_sclas.sh
```

Run the GUI on Windows from:

```bat
run_sclas.bat
```

The current main GUI is `code/sclas_remote_gui.py`. The copy in
`code/SCLAS_test/sclas_remote_gui.py` is kept synchronized for test use.
The launcher uses the existing virtual environment under `../90_env` because
the system `python3` may not have `numpy`, `PyQt5`, and `pyqtgraph` installed.
On Windows, run `setup_windows.bat` first to create `.venv` and install
`requirements.txt`.

Run the local smoke checks with:

```bat
run_self_check.bat
```

Inspect a generated or copied Abaqus job folder without Abaqus:

```bash
python code/sclas_job_summary.py --latest
python code/sclas_job_summary.py jobs/SCLAS_jobs/<job_folder>
python code/sclas_project_status.py
python code/sclas_project_status.py --save-report --save-markdown
python code/sclas_curve_compare.py
python code/sclas_curve_compare.py \
  --endpoint jobs/SCLAS_jobs/<endpoint_sweep_folder> \
  --continuous jobs/SCLAS_jobs/<continuous_curve_folder>
python code/sclas_curve_compare.py --save-report --save-markdown
python code/sclas_offline_diagnostics.py jobs/SCLAS_jobs/<job_folder>
python code/sclas_offline_diagnostics.py jobs/SCLAS_jobs/<job_folder> --save-report
python code/sclas_offline_diagnostics.py jobs/SCLAS_jobs/<job_folder> --save-markdown
```

By default, `--latest`, `sclas_project_status.py`, `sclas_curve_compare.py`,
and the GUI Recent Jobs panel ignore synthetic `self_check*` folders. Add
`--include-self-check` only when validating the test fixtures themselves.

Use `sclas_job_summary.py` first when you only need the current health,
curve class, warning totals, and next action. Use
`sclas_offline_diagnostics.py` when you need the full JSON/Markdown report.
If a CurveV0 comparison report exists in a job folder, `sclas_job_summary.py`
also prints the comparison status, peak ratio, and branch deltas.
Use `sclas_curve_compare.py` after both endpoint sweep and continuous CurveV0
jobs exist. It compares peak moment scale, positive/negative branch moments at
the common curvature, and odd-symmetry indicators. With `--save-report` and
`--save-markdown`, it writes `curve_v0_comparison_report.json` and
`curve_v0_comparison_report.md` into the continuous CurveV0 job folder.
Use `sclas_project_status.py --save-report --save-markdown` for a handoff-ready
snapshot of latest job health, CurveV0 comparison, contact preload status, and
the next recommended action. It writes `project_status_report.json` and
`project_status_report.md` into the latest job folder when one exists.
For continuous CurveV0 jobs, both commands report the basic multi-point shape
check: positive branch, negative branch, return-to-zero rows, odd symmetry, and
maximum curvature/moment.
For ODB-backed jobs, the same commands also report curve scalar summaries and
top local-field output channels for contact pressure, opening, slip, shear, and
stress when those fields are present.
For Abaqus-generated jobs, they also report the contact clearance/preload
diagnostic from `abaqus_mesh_manifest.json` when available.
The offline diagnostics tool checks `result_data.csv`,
`result_summary.json`, `abaqus_mesh_manifest.json`, generated `.inp` keyword
placement, and `.dat`/`.msg`/`.sta` solver logs when those files exist.
It also adds a recommended next action so the next backend fix starts from the
first blocking issue instead of rereading the whole log.
The same report is also available in the GUI from
`Analysis -> Recent Jobs -> Diagnose selected`. The GUI saves
`offline_diagnostics_report.json` and `offline_diagnostics_report.md` in the
selected job folder. Use `Open folder` in the same Recent Jobs panel to open
the selected job folder in Finder or Windows Explorer.

## Job package contract

Each run creates a job folder under:

```text
jobs/SCLAS_jobs/job_YYYYMMDD_HHMMSS_xxxxxxxx/
```

The GUI writes:

- `input_data.json`: full backend input payload.
- `units_manifest.json`: unit conventions for backend developers.
- `BACKEND_CONTRACT.md`: required input/output contract.
- `abaqus_runner.py`: placeholder backend runner copied from `code/`.
- `study_scope`: inside `input_data.json`, tells the backend which local
  behavior assessments are enabled.

The backend must write:

- `result_data.csv` with columns `curvature_1_per_m,moment_kn_m`.
- `result_summary.json` optionally, for status and metrics.
- `abaqus_mesh_manifest.json` when mesh conversion is attempted.
- `sclas_mesh_model.cae` and `<job_name>_mesh.inp` when `abaqus_runner.py` is
  executed inside Abaqus/CAE.

GUI screenshots for review and team handoff are stored under:

```text
screenshots/gui/
```

## Backend modes

- `FAST GUI preview`: GUI-side approximate solver for quick visual checks.
- `Export job package only`: creates files for another backend developer.
- `Run local/shared-folder command`: runs the selected local Python interpreter
  against `abaqus_runner.py input_data.json` inside the job folder by default.
- `Run remote computer via SSH/scp`: uploads the job folder contents, runs the
  remote command, then downloads `result_data.csv`.

## Next backend step

The current `code/abaqus_runner.py` already creates a first-pass Abaqus mesh
scaffold from the GUI Mesh tab when run with:

```bash
abaqus cae noGUI=abaqus_runner.py -- input_data.json
```

It still uses a placeholder response curve for `result_data.csv`. Keep that CSV
header unchanged while adding real bending boundary conditions, contact, solve
submission, and ODB extraction.

Recommended Abaqus development order:

1. Verify the generated `.cae` and `.inp` mesh scaffold in Abaqus/CAE.
2. Add contact/friction definitions between armour and adjacent layers.
3. Add cyclic bending boundary conditions and submit a real analysis job.
4. Extract bending moment-curvature from the ODB into `result_data.csv`.
5. Add contact/friction stick-slip extraction to `result_summary.json`.
6. Add torsion and axial load cases as separate backend routines.
7. Add bird-caging/pressure-effect metrics as JSON summaries before expanding
   the GUI plots.
