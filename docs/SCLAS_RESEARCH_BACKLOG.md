# SCLAS Research Backlog

This backlog translates current submarine cable mechanics references and CAE
GUI patterns into implementation work that can be tracked without committing
local reference PDFs or private notes.

## Public references checked

- Dai et al. 2025, *Isogeometric contact analysis in subsea umbilical and power
  cables*: reinforces that contact interfaces and penalty/contact parameters are
  highly sensitive for subsea cable stress prediction. Public link:
  https://arxiv.org/abs/2507.00563
- Goyal, Perkins, and Lee 2007, *Writhing Dynamics of Cables with Self-contact*:
  useful background for low-tension torsion, twist-to-writhe conversion, and
  self-contact risk beyond the current local bending GUI scope. Public link:
  https://arxiv.org/abs/physics/0702198
- Goyal and Perkins 2007, *Modeling of Cables with High and Low Tension Zones
  using a Hybrid Rod-Catenary Formulation*: suggests separating global cable
  regions from local flexure/torsion zones when the SCLAS model later expands
  beyond a local periodic cell. Public link:
  https://arxiv.org/abs/physics/0702224
- FEATool Multiphysics GUI workflow: useful CAE UX reference because it exposes
  a clear Geometry -> Grid -> Equation -> Boundary -> Solve -> Post sequence
  and supports reproducible script export. Public link: https://www.featool.com/

## GUI implications

- Keep the current SCLAS navigation close to a CAE workflow:
  Design -> Mesh -> Analysis/Post.
- Keep generated job folders reproducible: every GUI run should preserve
  `input_data.json`, `units_manifest.json`, `BACKEND_CONTRACT.md`,
  `abaqus_runner.py`, `result_data.csv`, and optional `result_summary.json`.
- Surface backend status in the GUI instead of hiding it in files. A user should
  see whether a result is a FAST preview, a local runner output, an Abaqus mesh
  scaffold, or a final Abaqus solve.
- Treat `result_summary.json` as the place for research metrics that do not fit
  the primary bending moment-curvature CSV.

## Backend implementation queue

1. Preserve the CSV contract:
   `curvature_1_per_m,moment_kn_m`.
2. Replace the placeholder response with an Abaqus cyclic bending step.
3. Add contact/friction definitions between armour wires and adjacent layers.
   Start from the generated `numerical_model.contact_interfaces` list.
4. Sweep residual contact pressure, friction coefficient, and contact penalty
   stiffness; report convergence and sensitivity in `result_summary.json`.
5. Extract stick/slip state indicators and loop energy from the ODB.
6. Add axial-torsion coupled load cases and write a stiffness matrix summary.
7. Add pressure/compression sweeps and a bird-caging risk index.
8. Later, separate global cable behavior from local high-fidelity zones using
   a hybrid global/local modeling approach.

## Near-term SCLAS acceptance checks

- `run_sclas.bat` opens the GUI on Windows.
- `setup_windows.bat` can repair or recreate the local virtual environment.
- FAST preview creates a new ignored job folder with `result_data.csv` and
  `result_summary.json`.
- Local command mode using `python abaqus_runner.py input_data.json` creates
  `result_data.csv`, `result_summary.json`, and `abaqus_mesh_manifest.json`.
- Abaqus mode using `abaqus cae noGUI=abaqus_runner.py -- input_data.json`
  creates `.cae` and `.inp` scaffold files before the real solve is added.
