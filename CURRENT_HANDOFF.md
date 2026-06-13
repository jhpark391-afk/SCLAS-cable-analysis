# CURRENT_HANDOFF

Last updated: 2026-06-14

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

Continue preparing the Abaqus backend to move from a placeholder/scaffold
runner toward a literature-informed nonlinear bending workflow. The GUI is
currently usable enough; the immediate next work is lab-PC Abaqus solver smoke
testing of the generated `.inp` after the latest coupling fallback fix.

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
- Mac-side self-check now uses a GUI-like rich backend payload instead of the
  legacy minimal sample. It verifies contact binding scaffold records,
  contact defaults, annular layer component names, enabled assessment
  propagation, result CSV row count, backend readiness keys, and placeholder
  derived metric fields without needing Abaqus.
- Mac-side offline diagnostics are now available through
  `code/sclas_offline_diagnostics.py`. The tool inspects copied job folders for
  CSV/summary/manifest contract shape, generated `.inp` coupling keyword
  placement, and `.dat`/`.msg`/`.sta` solver log error context without needing
  Abaqus.
- The Analysis page Recent Jobs panel now has `Diagnose selected`, which runs
  the offline diagnostics report on the selected job folder and writes the
  summary into the GUI result summary panel.
- GUI diagnostics and CLI `--save-report` now write
  `offline_diagnostics_report.json` into the inspected job folder for sharing
  between Mac, home Windows, and the Lab PC.
- CLI `--save-markdown` and GUI diagnostics now also write
  `offline_diagnostics_report.md`, including a human-readable issue summary,
  solver log context blocks, and a ready-to-paste next-debug prompt.
- Offline diagnostics now include `diagnostic_summary` with issue counts, the
  first blocking issue, and a recommended next action. The GUI summary panel
  shows this at the top of `Diagnose selected` output.
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
- The mesh scaffold now separates the main polymer layers into annular parts:
  `InnerSheathEquivalent`, `BeddingEquivalent`, and `OuterSheathEquivalent`.
  Their assembly surfaces use the GUI contract names
  `inner_sheath_inner_surface`, `inner_sheath_outer_surface`,
  `bedding_inner_surface`, `bedding_outer_surface`,
  `outer_sheath_inner_surface`, and `outer_sheath_outer_surface`. The manifest
  resolves declared contact bindings to these assembly surfaces and the armour
  `*_ContactEdges` sets, but explicit pair interactions are still pending.
- The runner now attempts B31 armour circumferential contact surfaces
  (`InnerArmourHelix_ContactSurface`, `OuterArmourHelix_ContactSurface`) and
  explicit `SurfaceToSurfaceContactStd` pair interactions for the declared GUI
  contact interfaces. Results are recorded under `contact_pair_scaffold`.
  Abaqus 2019 beam/surface contact support must be checked on the lab PC; pair
  records may be `created`, `partial`, `skipped`, or `failed` without changing
  the placeholder CSV contract.
- The runner now creates a cyclic bending boundary-condition scaffold:
  `SCLAS_CyclicBendingStep`, `SCLAS_CyclicBendingAmplitude`,
  `SCLAS_RP_LeftEnd`, `SCLAS_RP_RightEnd`, end-face surfaces, kinematic
  couplings, and a right-end cyclic rotation BC derived from GUI max curvature
  and effective length. Results are recorded under
  `boundary_condition_scaffold`. This is still a setup scaffold; no real Abaqus
  solve or ODB moment extraction is performed yet.
- Lab Abaqus 2019 created the cyclic step, amplitude, reference points, and
  reference-point BCs, but reported `partial` because assembly end surfaces
  failed and the model object exposed no `Coupling` method. The runner now
  separates required reference-point BC creation from optional end-face
  coupling, records end-face sets separately, and uses
  `created_with_pending_end_coupling` when the mandatory scaffold is present
  but Abaqus coupling support still needs a version-specific fallback.
- The runner now injects an Abaqus 2019-compatible keyword fallback into the
  generated `.inp` after `writeInput()`: end-node `*Nset`s, node-based
  `*Surface`s, and `*Coupling` / `*Kinematic` blocks are injected around
  `*End Assembly` using Abaqus input-deck scoping rules. If injection succeeds
  the boundary-condition status becomes
  `created_with_keyword_coupling_fallback`. This affects the generated input
  deck; the CAE model tree may still show only the Python-created reference
  points and BCs.
- A solver smoke submit with `*Coupling` / `*Kinematic` placed after
  `*End Assembly` stopped during Abaqus input processing with:
  `***ERROR: in keyword *COUPLING ... The keyword is misplaced. It can be
  suboption for ... assembly, instance, part`. The fallback now injects the
  end-node `*Nset`s, node-based `*Surface`s, and both coupling blocks before
  `*End Assembly` so all coupling data stays inside assembly scope. The next
  lab PC solver smoke test should check whether any remaining fatal errors are
  reference-node/surface syntax issues rather than keyword placement.
- `code/abaqus_runner.py` is still not a complete research-grade Abaqus solver.

## End-of-Day Handoff - 2026-06-12 KST

Latest pushed commit:

```text
ba9ce36 Keep Abaqus coupling fallback inside assembly
```

What was verified today:

- Lab PC RDP/ZeroTier access worked.
- Git and Python were made usable enough on the lab PC to pull and run the
  repository.
- The GUI launched on the lab PC.
- Abaqus/CAE 2019 noGUI ran `code/abaqus_runner.py` and checked out a CAE
  license successfully.
- The generated job folder produced `result_data.csv`, `result_summary.json`,
  `abaqus_mesh_manifest.json`, `sclas_mesh_model.cae`, and a large generated
  `.inp`.
- Visual CAE inspection confirmed a meshed cable scaffold exists.
- CAE model tree checks confirmed the expected scaffold objects were present:
  parts, contact property, contact/general-contact or pair scaffold objects,
  cyclic bending step, amplitude, reference points, and BC scaffolding.
- Abaqus/Standard solver submission reached input processing.

Most recent solver issue:

- The generated `.inp` failed because `*Coupling` had been moved after
  `*End Assembly`.
- Abaqus reported:
  `***ERROR: in keyword *COUPLING ... The keyword is misplaced. It can be
  suboption for ... assembly, instance, part`.
- Commit `ba9ce36` fixes this by placing `*Coupling` / `*Kinematic` inside the
  assembly block before `*End Assembly`, together with the node sets and
  node-based end surfaces.

Important context:

- The lab PC's Abaqus 2019 noGUI Python behaves like Python 2, so keep
  `code/abaqus_runner.py` compatible with Python 2-era syntax.
- Do not commit generated job folders, `.cae`, `.odb`, `.inp`, `.prt`, `.sim`,
  `.dat`, or large reference files.
- The repository may contain unrelated local dirty files on the home Codex
  machine. Only stage files intentionally changed for the task.

Immediate next lab-PC command sequence:

```powershell
cd $env:USERPROFILE\Documents\SCLAS-cable-analysis
git pull

$JobDir = "C:\Users\user\Documents\SCLAS-cable-analysis\jobs\SCLAS_jobs\job_20260611_231236_85a1760e"
Copy-Item code\abaqus_runner.py $JobDir\abaqus_runner.py -Force

Push-Location $JobDir
cmd /c "abaqus cae noGUI=abaqus_runner.py -- input_data.json > abaqus_stdout.txt 2>&1"
Pop-Location

$Inp = Get-ChildItem $JobDir -Filter "*_mes.inp" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$JobName = [IO.Path]::GetFileNameWithoutExtension($Inp.Name)

Push-Location $JobDir
cmd /c "abaqus job=$JobName input=$($Inp.Name) interactive > solver_stdout.txt 2>&1"
Pop-Location

Get-Content "$JobDir\solver_stdout.txt" -Raw
Select-String -Path "$JobDir\$JobName.dat" -Pattern "FATAL|ERROR|UNKNOWN|INVALID|COUPLING|KINEMATIC|REF NODE|SURFACE" -Context 2,3 | Select-Object -First 100
```

Expected next result:

- If the old placement error is gone, inspect any new `.dat` fatal lines. The
  next likely class of issues is reference-node or node-surface syntax, not GUI
  wiring.
- If solver input processing proceeds further, start reducing model size for a
  faster real smoke solve before implementing ODB extraction.

## Mac-Side Handoff - 2026-06-13 KST

What was done on the Mac after pulling the home/Lab-PC work:

- Pulled GitHub `main` through commit `a63c674`.
- Read `AGENTS.md`, `CURRENT_HANDOFF.md`, `README_SCLAS_WORKFLOW.md`, and
  `README_LITERATURE_NOTES.md`.
- Verified that the pulled GUI/backend files compile on macOS:

```bash
../90_env/venv/bin/python -m py_compile code/sclas_remote_gui.py code/SCLAS_test/sclas_remote_gui.py code/abaqus_runner.py code/SCLAS_test/abaqus_runner.py
```

- Verified the project smoke check:

```bash
../90_env/venv/bin/python code/sclas_self_check.py
```

- Strengthened `code/sclas_self_check.py` so normal Python catches more
  backend contract regressions before Lab-PC Abaqus testing.
- Added `code/sclas_offline_diagnostics.py` and wired it into
  `code/sclas_self_check.py`.
- Added GUI access to the same offline diagnostics from Analysis > Recent Jobs
  through `Diagnose selected`.

Run offline diagnostics on any copied Lab-PC job folder:

```bash
../90_env/venv/bin/python code/sclas_offline_diagnostics.py jobs/SCLAS_jobs/<job_folder>
```

Machine-readable mode:

```bash
../90_env/venv/bin/python code/sclas_offline_diagnostics.py jobs/SCLAS_jobs/<job_folder> --json
```

Save a shareable JSON report:

```bash
../90_env/venv/bin/python code/sclas_offline_diagnostics.py jobs/SCLAS_jobs/<job_folder> --save-report
```

Save a human-readable Markdown report:

```bash
../90_env/venv/bin/python code/sclas_offline_diagnostics.py jobs/SCLAS_jobs/<job_folder> --save-markdown
```

Mac-appropriate next work:

1. Keep improving non-Abaqus contract checks and result post-processing.
2. When Lab-PC `.inp`, `.dat`, `.msg`, or `.sta` files are copied back, run
   `code/sclas_offline_diagnostics.py` and use the first reported fatal/error
   context to guide the next targeted backend fix.
3. Add sample-result comparison/reporting features in the GUI if needed.
4. Keep `CURRENT_HANDOFF.md` updated after each Mac-side support task.
5. Leave actual Abaqus solve/input-deck debugging to the Lab PC unless the user
   provides generated `.inp`, `.dat`, or `.msg` files for offline inspection.

## Home Pull / Lab Smoke Helper - 2026-06-14 KST

The home Windows Codex pulled Mac-side commits through:

```text
17dcd78 Summarize diagnostic next actions
```

Local verification after the pull passed:

```powershell
python -m py_compile code\sclas_remote_gui.py code\SCLAS_test\sclas_remote_gui.py code\abaqus_runner.py code\SCLAS_test\abaqus_runner.py code\sclas_offline_diagnostics.py
python code\sclas_self_check.py
python code\sclas_offline_diagnostics.py jobs\SCLAS_jobs\self_check_20260614_001952
```

To reduce copy/paste mistakes on the Lab PC, use the new helper script after
pulling the latest repository:

```powershell
cd $env:USERPROFILE\Documents\SCLAS-cable-analysis
git pull
powershell -ExecutionPolicy Bypass -File .\run_lab_abaqus_smoke.ps1 -JobDir "C:\Users\user\Documents\SCLAS-cable-analysis\jobs\SCLAS_jobs\job_20260611_231236_85a1760e"
```

If no `-JobDir` is passed, the script uses the newest `jobs\SCLAS_jobs\job_*`
folder with `input_data.json`. It copies the latest `code\abaqus_runner.py`
into the job folder, runs Abaqus/CAE noGUI generation, submits the generated
`*_mes.inp` to Abaqus/Standard, writes `solver_error_extract.txt`, and, when
normal Python is available, saves `offline_diagnostics_report.json` and
`offline_diagnostics_report.md`.

After the first Lab-PC run with this helper, `solver_error_extract.txt` was
polluted by normal `CONTACTSURFACE` lines because the extractor searched broad
terms such as `SURFACE` before true fatal/error markers. The helper and
`code/sclas_offline_diagnostics.py` now search blocking patterns first
(`***ERROR`, `FATAL`, `Abaqus Error`, `THE PROGRAM HAS DISCOVERED`, etc.) and
only fall back to notable terms like coupling/reference-node warnings if no
blocking lines are found.

The next Lab-PC `.dat` inspection showed that the old `*COUPLING misplaced`
error is gone. Abaqus now stops on two explicit contact-pair errors:

```text
***ERROR: SURFACE ASSEMBLY_OUTERARMOURHELIX_CONTACTSURFACE IS MADE UP OF 3D
          LINE ELEMENTS AND CANNOT BE USED AS A MASTER SURFACE
***ERROR: SURFACE ASSEMBLY_INNERARMOURHELIX_CONTACTSURFACE IS MADE UP OF 3D
          LINE ELEMENTS AND CANNOT BE USED AS A MASTER SURFACE
```

The runner now tags armour conceptual regions as `surface_kind=beam_line` and
solid layer surfaces as `surface_kind=solid_face`. Explicit contact-pair
creation avoids any solver attempt where a B31 beam-line armour surface is the
master. For solid-vs-armour pairs, it swaps the solver order so the solid face
is master and the beam surface is slave. For armour-vs-armour pairs, it skips
the explicit pair and leaves that interaction to the general-contact scaffold
until a solid/contact-surface armour representation is implemented.

The next Lab-PC run reached the Abaqus/Standard `standard` process, which means
input processing got past the previous coupling and B31-master-surface fatal
errors. The existing full job is too large for quick smoke solving, so
`run_lab_abaqus_smoke.ps1` now has `-SmallSmoke`. This creates a new lightweight
job folder from the selected source job, copies only the contract files, lowers
mesh settings, updates `metadata.job_id`, and leaves the original job untouched.

Use this on the Lab PC for the next fast solver check:

```powershell
cd $env:USERPROFILE\Documents\SCLAS-cable-analysis
git pull
powershell -ExecutionPolicy Bypass -File .\run_lab_abaqus_smoke.ps1 -JobDir "C:\Users\user\Documents\SCLAS-cable-analysis\jobs\SCLAS_jobs\job_20260611_231236_85a1760e" -SmallSmoke
```

Optional knobs:

```powershell
-SmallAxialDivisions 4 -SmallCoreCircumferentialDivisions 8 -SmallArmourCircumferentialDivisions 4 -SmallEffectiveLengthMm 50
```

The first `-SmallSmoke` attempt failed before mesh generation because
PowerShell rewrote `input_data.json` with a UTF-8 BOM, which Abaqus 2019's
Python 2.7 `json.load` reported as `ValueError: No JSON object could be
decoded`. The helper now writes the reduced JSON as UTF-8 without BOM, and
`code/abaqus_runner.py` defensively strips UTF-8 BOM / decodes UTF-16 input
payloads before `json.loads`.

The next `-SmallSmoke` generation succeeded, but the helper did not find the
input deck because small job names produce `small_smoke_..._mesh.inp` while the
old helper only searched for `*_mes.inp` from truncated long job names. The
helper now accepts both `*_mesh.inp` and `*_mes.inp`.

The small smoke solver run then completed successfully:

```text
Abaqus JOB small_smoke_20260614_011324_mesh COMPLETED
```

This confirms that the current scaffold can pass Abaqus input processing and a
small Abaqus/Standard solve after the coupling-scope and B31 master-surface
fixes. The solver logs still contain modelling warnings such as distorted
elements, zero-pivot/overconstraint checks on armour beam nodes, and contact
adjustment notes. These are not blocking for the smoke milestone because Abaqus
completed the job. Diagnostics now detect solver completion first and avoid
treating completed-job warning vocabulary as a blocking error. Next backend
work should focus on ODB extraction into `result_data.csv`, then tightening
contact/BC modelling quality for the full-size job.

ODB extraction work has started:

- `code/sclas_odb_extractor.py` was added as an Abaqus-Python script.
- `run_lab_abaqus_smoke.ps1` now copies it into the job folder and, when the
  solver completes and an `.odb` exists, runs:
  `abaqus python sclas_odb_extractor.py <job>.odb --job-dir .`.
- The extractor tries `UR2` / `RM2` history output first, then field output on
  the right reference point set. If successful, it overwrites
  `result_data.csv` with ODB-derived `curvature_1_per_m,moment_kn_m` and writes
  `odb_extraction_summary.json`; if not, it preserves the placeholder CSV and
  records the missing-output reason.
- New input decks request `U`, `UR`, `RF`, `RM` field output and right-RP
  `UR2`/`RM2` history output to improve extraction reliability.

Next Lab-PC check:

```powershell
cd $env:USERPROFILE\Documents\SCLAS-cable-analysis
git pull
powershell -ExecutionPolicy Bypass -File .\run_lab_abaqus_smoke.ps1 -JobDir "C:\Users\user\Documents\SCLAS-cable-analysis\jobs\SCLAS_jobs\job_20260611_231236_85a1760e" -SmallSmoke
```

Use a newly generated small smoke job for this check so the output requests are
present in the `.inp` and `.odb`.

## Lab ODB Smoke Success - 2026-06-14 KST

The Lab PC pulled commit:

```text
9fa51ed Add initial Abaqus ODB extraction
```

Then this command was run from
`C:\Users\user\Documents\SCLAS-cable-analysis`:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_lab_abaqus_smoke.ps1 -JobDir "C:\Users\user\Documents\SCLAS-cable-analysis\jobs\SCLAS_jobs\job_20260611_231236_85a1760e" -SmallSmoke
```

The helper created:

```text
jobs\SCLAS_jobs\small_smoke_20260614_013239
```

Verified result:

- Abaqus/CAE noGUI generation completed with `Exit code: 0`.
- Mesh status was `abaqus_mesh_created`.
- Boundary condition scaffold status was
  `created_with_keyword_coupling_fallback`.
- Abaqus/Standard completed:
  `Abaqus JOB small_smoke_20260614_013239_mesh COMPLETED`.
- ODB extraction succeeded with `status: extracted`.
- `result_data.csv` was updated by `SCLAS_ABAQUS_ODB_EXTRACTOR`.
- Offline diagnostics reported:
  `Issue counts: {'error': 0, 'warning': 0, 'info': 0}`,
  `completed: True`, and `failed: False`.

ODB extraction summary:

```json
{
    "status": "extracted",
    "method": "field",
    "node_set": "SCLAS_RP_RIGHTEND",
    "step": "SCLAS_CyclicBendingStep",
    "rotation_output": "UR2",
    "moment_output": "RM2",
    "effective_length_mm": 50.0,
    "frames_used": 2,
    "rows_written": 2
}
```

This is the first end-to-end backend smoke milestone:

```text
GUI job package -> Abaqus/CAE noGUI mesh/input deck -> Abaqus/Standard solve -> ODB extraction -> result_data.csv/result_summary.json -> offline diagnostics
```

Important limitation:

- `rows_written` is only 2, so this is still a connection/extraction smoke
  test, not a useful moment-curvature loop.
- The next backend task is to force more Abaqus increments/output frames so the
  extractor produces a multi-point curve.

This handoff update also adds a small runner/helper change for the next Lab-PC
test:

- `code/abaqus_runner.py` reads
  `analysis_conditions.abaqus_output_intervals` and uses it to set cyclic-step
  `initialInc` / `maxInc`.
- Field and history output requests now use `frequency=1`.
- `run_lab_abaqus_smoke.ps1 -SmallSmoke` now writes
  `abaqus_output_intervals=12` by default and exposes
  `-SmallAbaqusOutputIntervals`.

Next Lab-PC command after pulling the next commit:

```powershell
cd $env:USERPROFILE\Documents\SCLAS-cable-analysis
git pull
powershell -ExecutionPolicy Bypass -File .\run_lab_abaqus_smoke.ps1 -JobDir "C:\Users\user\Documents\SCLAS-cable-analysis\jobs\SCLAS_jobs\job_20260611_231236_85a1760e" -SmallSmoke
```

Expected next check:

- `ODB extraction status: extracted`
- `result_summary.json` source remains `SCLAS_ABAQUS_ODB_EXTRACTOR`
- `odb_rows_written` should be greater than 2, ideally about 10-13 rows for the
  default 12 intervals.

## Important Files

```text
code/sclas_remote_gui.py
code/SCLAS_test/sclas_remote_gui.py
code/sclas_remote_gui_final_code.txt
code/abaqus_runner.py
code/SCLAS_test/abaqus_runner.py
run_lab_abaqus_smoke.ps1
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
model tree should show this under Interactions. For separated layer geometry,
also verify that `Parts` includes `InnerSheathEquivalent`, `BeddingEquivalent`,
and `OuterSheathEquivalent`, and that assembly Surfaces include the six
contract-named layer surfaces above. For explicit contact-pair checks, inspect
`contact_pair_scaffold` in the manifest and verify any created `Pair_*`
interactions in the CAE tree. For cyclic bending setup checks, inspect
`boundary_condition_scaffold` and verify `SCLAS_CyclicBendingStep`,
`SCLAS_CyclicBendingAmplitude`, end reference point sets, and BCs in the CAE
model tree. If the status is `created_with_pending_end_coupling`, inspect
`optional_warnings` and `available_constraint_methods` before implementing the
version-specific coupling fallback. If the status is
`created_with_keyword_coupling_fallback`, inspect the generated `.inp` for
`SCLAS_LeftEnd_KeywordCoupling` and `SCLAS_RightEnd_KeywordCoupling`.

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

1. On the lab PC, pull commit `ba9ce36` and re-run the Abaqus noGUI generation
   plus solver smoke command sequence above.
2. If the solver still fails during input processing, capture the first
   `FATAL` / `ERROR` block from the `.dat` file and fix only that Abaqus input
   issue.
3. If input processing succeeds, make a reduced-size smoke model so Abaqus
   solve iterations are fast enough for backend development.
4. Preserve the GUI contract:
   - `input_data.json` as backend input
   - `result_data.csv` with `curvature_1_per_m,moment_kn_m`
   - `result_summary.json` for optional metrics
5. Add true periodic boundary equations or a documented equivalent-cell
   approximation.
6. Add Abaqus job submission/status handling and ODB extraction into
   `result_data.csv`.
7. After each meaningful task, update this file, commit, and push.

## Home Codex Start Prompt

Use this prompt when starting work on the home or Mac Codex computer:

```text
This is the HELIX / SCLAS submarine cable analysis repository.

First run git pull and git status. Then read AGENTS.md and CURRENT_HANDOFF.md.
Summarize the current project state, the latest handoff, and the next task.

Before editing, tell me which files you will touch. After editing, run the
project verification commands. If code/sclas_remote_gui.py changes, sync it to
code/SCLAS_test/sclas_remote_gui.py and code/sclas_remote_gui_final_code.txt.

The GUI is currently usable. The immediate priority is to continue the lab-PC
Abaqus solver smoke test after commit ba9ce36, inspect the next .dat error if
any, and continue preparing code/abaqus_runner.py for real Abaqus contact,
periodic boundary conditions, cyclic bending, job submission, and ODB result
extraction.
```
