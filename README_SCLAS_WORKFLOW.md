# SCLAS Workflow

## Research goal

SCLAS is being developed as an integrated framework for evaluating local
behavior of submarine power cables. The primary workflow is:

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

## Backend modes

- `FAST GUI preview`: GUI-side approximate solver for quick visual checks.
- `Export job package only`: creates files for another backend developer.
- `Run local/shared-folder command`: runs `python3 abaqus_runner.py input_data.json`
  inside the job folder by default.
- `Run remote computer via SSH/scp`: uploads the job folder contents, runs the
  remote command, then downloads `result_data.csv`.

## Next backend step

Replace `run_placeholder_solver` in `code/abaqus_runner.py` with the real Abaqus
model generation and ODB extraction. Keep the CSV output header unchanged so the
GUI continues to load results without modification.

Recommended Abaqus development order:

1. Keep bending moment-curvature CSV output stable.
2. Add contact/friction stick-slip extraction to `result_summary.json`.
3. Add torsion and axial load cases as separate backend routines.
4. Add bird-caging/pressure-effect metrics as JSON summaries before expanding
   the GUI plots.
