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
- The next backend task is to request more ODB output frames without forcing
  smaller Abaqus solver increments.

This handoff update also adds a small runner/helper change for the next Lab-PC
test:

- `code/abaqus_runner.py` reads
  `analysis_conditions.abaqus_output_intervals` for ODB output request
  intervals only. The cyclic step now leaves Abaqus solver increment control at
  the Abaqus default.
- Field and history output requests first try `numIntervals` with
  `timeMarks=OFF`, then fall back to `frequency=1`, then to Abaqus defaults.
- `run_lab_abaqus_smoke.ps1 -SmallSmoke` now writes
  `abaqus_output_intervals=4` by default and exposes
  `-SmallAbaqusOutputIntervals`.

Follow-up from Lab PC:

- A run with `-SmallAbaqusOutputIntervals 12` created
  `small_smoke_20260614_014418`, but the solve was intentionally terminated by
  the user after it remained near `STEP TIME/LPF = 0.0495` while CPU time was
  still increasing. Abaqus reported
  `Process terminated by external request (SIGTERM or SIGINT received)`, which
  is expected for this manual termination.
- The 12-interval smoke is too slow for the current contact/nonlinear scaffold,
  so the default has been lowered to 4 intervals. Use a higher value only after
  a 4-interval smoke confirms ODB extraction still succeeds.
- A follow-up 4-interval run, `small_smoke_20260614_020228`, was also
  intentionally terminated because the forced-increment version remained at
  `STEP TIME/LPF = 0.00` after repeated first-increment cutbacks. This confirms
  that forcing `StaticStep(initialInc/maxInc)` is the wrong approach for this
  scaffold.
- The next commit removes the forced `initialInc` / `maxInc` controls and keeps
  only output-request interval hints, so the Lab PC should regain the earlier
  fast solve behavior while still attempting more ODB output rows.
- After that fix, `small_smoke_20260614_021258` completed quickly again and
  ODB extraction succeeded, but `rows_written` remained 2. This shows the CAE
  output-request API hints did not increase ODB frame count on Abaqus 2019.
- The input-deck output keyword fallback was then tested in
  `small_smoke_20260614_022141`. Abaqus accepted the keywords and completed,
  but `history_rows_available` and `field_rows_available` were both still 2.
  This means the step solved in a single increment, so ODB output requests
  alone cannot create intermediate frames.
- The four-step smoke path `+target -> 0 -> -target -> 0` was added as a
  candidate way to get more ODB rows, but Lab-PC feedback showed it takes too
  long for an interactive smoke loop. `-SmallSmoke` therefore defaults back to
  the fast single-step path; the four-step path is now opt-in through
  `-MultiStepSmoke`.
- When `-MultiStepSmoke` is used, the ODB extractor concatenates all
  `SCLAS_CyclicBendingStep*` steps into one CSV. Use it only when a longer run
  is acceptable.
- The runner still injects an input-deck output keyword fallback before each
  `*End Step`:
  `*Output, field, number interval=4, time marks=NO` plus right-reference-point
  `*Node Output`. The ODB extractor now compares history and field extraction
  counts across all bending steps and chooses the method with more rows.

Next Lab-PC command after pulling the next commit:

```powershell
cd $env:USERPROFILE\Documents\SCLAS-cable-analysis
git pull
powershell -ExecutionPolicy Bypass -File .\run_lab_abaqus_smoke.ps1 -JobDir "C:\Users\user\Documents\SCLAS-cable-analysis\jobs\SCLAS_jobs\job_20260611_231236_85a1760e" -SmallSmoke
```

Expected next check:

- `ODB extraction status: extracted`
- `result_summary.json` source remains `SCLAS_ABAQUS_ODB_EXTRACTOR`
- default `-SmallSmoke` should complete quickly and may still write 2 rows.
- only `-SmallSmoke -MultiStepSmoke` is expected to produce more than 2 rows,
  but it may take noticeably longer.
- `odb_extraction_summary.json` should include `history_rows_available` and
  `field_rows_available`.

Latest Lab-PC follow-up:

- Default fast `-SmallSmoke` created `small_smoke_20260614_024055` and Abaqus
  completed quickly again, but ODB extraction failed after the multistep
  extractor change.
- The likely cause was overly aggressive row de-duplication: the extractor
  removed duplicate-looking rows even within a single step, which can collapse
  the two-frame smoke output below the minimum two rows.
- The extractor now only removes a duplicate first row when concatenating a new
  step to a previous step. Rows within a single step are preserved.
- After pulling that fix, default fast `-SmallSmoke` created
  `small_smoke_20260614_024704` with `multistep_smoke=False`. Abaqus/Standard
  completed, ODB extraction succeeded, and diagnostics reported no issues:
  `history_rows_available=2`, `field_rows_available=2`, `rows_written=2`,
  `source=SCLAS_ABAQUS_ODB_EXTRACTOR`, `completed=True`, `failed=False`.
- Treat this as the current stable Lab-PC backend smoke baseline. The
  end-to-end bridge is confirmed for a fast two-row ODB extraction:
  `input_data.json -> Abaqus .inp/.odb -> result_data.csv/result_summary.json`.
- Do not spend more interactive Lab-PC time trying to force more rows with
  small smoke. Multi-point curves should be designed as a separate backend
  task, likely with a lower-cost load path or different step/output strategy.

## Real Curve v0 Preparation - 2026-06-14 KST

After the stable Lab-PC smoke baseline, the next step moved back to code/docs
instead of more interactive Lab-PC runs.

Changes prepared for the next commit:

- `code/sclas_odb_extractor.py` now writes
  `result_summary.json.abaqus_result_quality`.
- A two-row successful extraction is classified as
  `curve_class=two_point_odb_smoke`, `is_research_curve=false`, and
  `backend_readiness.bending_stick_slip.status=abaqus_odb_smoke_two_point`.
- Five or more valid ODB rows are classified as
  `curve_class=multi_point_curve_v0`, `is_research_curve=true`, and
  `backend_readiness.bending_stick_slip.status=abaqus_odb_curve_v0`.
- `code/sclas_offline_diagnostics.py` now reports the curve class and gives a
  different recommended next action for stable two-row smoke versus a real
  multi-point curve.
- `docs/ABAQUS_BACKEND_IMPLEMENTATION_PLAN.md` now records the verified
  Lab-PC baseline and separates `real moment-curvature curve v0` from the fast
  `-SmallSmoke` bridge check.

Next implementation target:

- Add an explicit curve-v0 mode separate from default `-SmallSmoke`.
- Use a deliberate reduced-cost load path with at least five accepted ODB rows.
- Keep Abaqus solver increment control automatic unless a later diagnostic
  proves a specific increment setting is needed.

Implemented next:

- The previous one-model multi-step `-CurveV0` attempt was too slow for the
  current nonlinear contact scaffold.
- Curve-v0 is now redesigned as an endpoint sweep:
  each curvature factor runs as its own reduced, single-step Abaqus job with no
  cyclic amplitude and no forced solver increments.
- `run_lab_abaqus_smoke.ps1 -CurveV0 -CurveV0CurvatureScale <factor>` now
  creates a single endpoint job.
- New `run_curve_v0_sweep.ps1` automates the proper v0 workflow: it runs
  several endpoint jobs and aggregates each final ODB row into
  `curve_v0_sweep_.../result_data.csv`.
- Default factors are `-0.1, -0.05, 0, 0.05, 0.1`.
- The sweep helper now validates every child job before aggregation:
  `result_summary.json.source` must be `SCLAS_ABAQUS_ODB_EXTRACTOR`,
  `odb_extraction.status` must be `extracted`, and at least two ODB rows must
  exist. This prevents a failed child or leftover placeholder CSV from being
  silently included in the parent curve.
- Parent sweep summaries are classified as candidate endpoint curves, not
  validated research hysteresis loops. Use them to check shape and monotonic
  response before attempting a continuous cyclic bending path.

Next Lab-PC curve-v0 sweep command:

```powershell
cd $env:USERPROFILE\Documents\SCLAS-cable-analysis
git pull
powershell -ExecutionPolicy Bypass -File .\run_curve_v0_sweep.ps1 -JobDir "C:\Users\user\Documents\SCLAS-cable-analysis\jobs\SCLAS_jobs\job_20260611_231236_85a1760e"
```

Expected:

- It will run five small child jobs, so it takes longer than one `-SmallSmoke`,
  but each child should behave like a stable single-step endpoint solve.
- Parent output should be
  `jobs\SCLAS_jobs\curve_v0_sweep_...\result_data.csv` with five rows.
- If even the first endpoint point is too slow, stop and rerun with fewer or
  smaller factors, for example:
  `-CurveFactors -0.05,0,0.05`.

## Lab Curve V0 Endpoint Sweep Success - 2026-06-14 KST

The Lab PC pulled/verified the latest repository state at:

```text
506b871 Fix CurveV0 sweep row formatting
```

First `git pull --ff-only` needed unrestricted filesystem/network access to
write `.git/FETCH_HEAD`; after approval it reported `Already up to date`.

Fast bridge smoke was rerun with:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_lab_abaqus_smoke.ps1 -SmallSmoke
```

The first sandboxed attempt could not reach the FlexNet license server:

```text
FlexNet Licensing error:-15,10. System Error: 10013 "WinSock: Access denied"
```

The same command succeeded after running with license/network access. It
created:

```text
jobs\SCLAS_jobs\small_smoke_20260614_035856
```

Verified:

- Abaqus/Standard completed:
  `Abaqus JOB small_smoke_20260614_035856_mesh COMPLETED`.
- ODB extraction status was `extracted`.
- `result_summary.json.source` was `SCLAS_ABAQUS_ODB_EXTRACTOR`.
- `odb_extraction.rows_written` was `2`.
- Offline diagnostics reported zero issues.

Then the Curve V0 endpoint sweep was run with default factors:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_curve_v0_sweep.ps1
```

The sweep created:

```text
jobs\SCLAS_jobs\curve_v0_sweep_20260614_040136
```

Parent sweep validation:

- `result_data.csv` exists with five data rows.
- `result_summary.json.source` is `SCLAS_CURVE_V0_ENDPOINT_SWEEP`.
- `endpoint_sweep_validation.all_child_jobs_validated` is `true`.
- `rows_written` is `5`.
- Aggregated endpoint rows:

```csv
curvature_1_per_m,moment_kn_m
-0.0079999997979,-0.84404125
-0.00399999989895,-0.4220246875
0,0
0.00399999989895,0.42202409375
0.0079999997979,0.8440385625
```

Child jobs:

```text
curve_v0_20260614_040136  factor=-0.1   rows_written=2
curve_v0_20260614_040456  factor=-0.05  rows_written=2
curve_v0_20260614_040749  factor=0      rows_written=2
curve_v0_20260614_041014  factor=0.05   rows_written=2
curve_v0_20260614_041308  factor=0.1    rows_written=2
```

For every child:

- `result_summary.json.source` was `SCLAS_ABAQUS_ODB_EXTRACTOR`.
- `odb_extraction.status` was `extracted`.
- `odb_extraction.rows_written` was `2`.
- The last CSV row was numeric and matched the parent aggregation.
- Searching `.dat`, `.msg`, and `.sta` for
  `ERROR|FATAL|INVALID|MISPLACED|OVERCONSTRAINT` found zero hits.

No code fix was needed for this run. The first blocking issue encountered was
environmental only: sandboxed Abaqus could not reach the license server. Running
the Abaqus helpers with license/network access resolved it.

Local normal Python on the Lab PC needs attention:

- `python` is not on `PATH`.
- `.venv\Scripts\python.exe` exists but points to a missing
  `C:\Users\user\AppData\Local\Programs\Python\Python312\python.exe`.
- Verification was therefore run with the Codex bundled Python:

```powershell
C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m py_compile code\abaqus_runner.py code\SCLAS_test\abaqus_runner.py code\sclas_odb_extractor.py code\sclas_offline_diagnostics.py
C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe code\sclas_self_check.py
```

Both commands passed. `code\sclas_self_check.py` created:

```text
jobs\SCLAS_jobs\self_check_20260614_041730
jobs\SCLAS_jobs\self_check_endpoint_sweep_20260614_041730
```

Do not commit generated job artifacts from these runs.

Recommended next backend work:

1. Keep `SmallSmoke` as the quick bridge health check.
2. Treat the current endpoint sweep as a candidate monotonic Curve V0 shape,
   not a validated research hysteresis loop.
3. Add a follow-up diagnostic/plot check for endpoint monotonicity, odd
   symmetry, and factor-to-curvature scaling.
4. Repair or recreate the Windows `.venv` when convenient so
   `run_self_check.bat` works without using the Codex bundled Python.
5. Start the next modelling increment only after this endpoint baseline is
   committed: better contact quality, periodic-equivalent constraints, or a
   reduced continuous bending path that does not exceed the 20-minute
   interactive limit.

Follow-up diagnostics hardening in the next commit:

- `code/sclas_offline_diagnostics.py` now adds
  `endpoint_sweep_shape` for parent sweep folders.
- The shape check verifies numeric CSV rows, monotonic curvature, monotonic
  moment, a near-zero endpoint, basic odd symmetry between +/- endpoints, child
  endpoint numeric values, and factor-to-curvature scale consistency.
- Endpoint sweep parent folders now skip manifest/input-deck/solver-log checks
  because those Abaqus artifacts live in the child job folders.
- The latest parent sweep
  `jobs\SCLAS_jobs\curve_v0_sweep_20260614_040136` passed the new checks with:

```text
shape_checks_passed=true
odd_symmetry_max_relative_moment_sum=3.184086085824686e-06
factor_curvature_scale=0.079999997979
factor_curvature_scale_max_relative_deviation=0.0
issue_counts={'error': 0, 'warning': 0, 'info': 0}
```

- `code\sclas_self_check.py` now includes this endpoint-shape diagnostics path.
- Verification was rerun with the Codex bundled Python:

```powershell
C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m py_compile code\abaqus_runner.py code\SCLAS_test\abaqus_runner.py code\sclas_odb_extractor.py code\sclas_offline_diagnostics.py
C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe code\sclas_self_check.py
```

Both commands passed.

Additional diagnostics hardening:

- `code/sclas_offline_diagnostics.py` now deep-validates endpoint sweep child
  jobs from the parent `child_jobs[*].path` records.
- For each child it checks:
  `result_summary.json`, `odb_extraction_summary.json`, `result_data.csv`,
  last-row numeric agreement with the parent aggregation, solver completion,
  solver failure flags, and blocking log keyword hits.
- Parent endpoint diagnostics now report `endpoint_sweep_children` with
  `all_children_deep_validated`, per-child CSV/ODB/log status, total blocking
  hits, and total notable warning hits.
- The real Lab sweep
  `jobs\SCLAS_jobs\curve_v0_sweep_20260614_040136` was rechecked with the new
  parent diagnostics:

```text
endpoint_sweep_children.all_children_deep_validated=true
endpoint_sweep_children.blocking_log_hits=0
endpoint_sweep_children.notable_log_hits=2137
diagnostic_summary.issue_counts={'error': 0, 'warning': 0, 'info': 0}
```

- The notable hits are completed-solver warnings/notes from child logs, not
  blocking errors. The next modelling task should reduce these warnings, but
  they do not invalidate the current Curve V0 endpoint baseline.
- Offline diagnostics now classifies completed-child notable log hits into
  warning categories so the next modelling target is visible without rereading
  the full `.dat`/`.msg` files. On
  `curve_v0_sweep_20260614_040136`, the largest categories were:

```text
numerical_singularity=1367
overconstraint_check=605
coupling_or_reference_node_note=60
other_warning=40
beam_contact_surface_to_node_fallback=20
increment_cutback_or_excessive_reporting=15
beam_curvature=10
distorted_elements=10
contact_pair_general_contact_overlap=5
unconnected_regions=5
```

- This points the next backend modelling work toward stabilizing armour beam
  constraints/contact and reducing numerical singularity/overconstraint warning
  volume. Do not treat these as blocking for the current endpoint baseline
  because all five child solvers completed and ODB extraction was validated.

## Lab Contact Keyword Adjustment - 2026-06-14 KST

The runner now post-processes generated Abaqus input decks so contact pairs
that include armour B31 beam-line contact surfaces are written explicitly as:

```text
*Contact Pair, interaction=SCLAS_RegularizedContact, type=NODE TO SURFACE
```

This matches the fallback Abaqus/Standard was already applying implicitly for
3D beam/truss slave surfaces, but removes the repeated warning:

```text
SURFACE TO SURFACE CONTACT APPROACH ... IS NOT YET AVAILABLE FOR 3D BEAM OR
TRUSS SLAVE SURFACE. NODE TO SURFACE APPROACH WILL BE USED INSTEAD.
```

Implementation details:

- `code/abaqus_runner.py` adds `adjust_beam_contact_pair_keywords()` after
  `writeInput()`.
- The function only changes generated `*Contact Pair` keyword lines whose data
  line contains a created beam-line contact surface.
- `abaqus_mesh_manifest.json.contact_pair_keyword_adjustment` records status,
  target type, adjusted count, beam surfaces, and adjusted pair data lines.
- `code/SCLAS_test/abaqus_runner.py` was synchronized.

Verification:

```powershell
C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m py_compile code\abaqus_runner.py code\SCLAS_test\abaqus_runner.py code\sclas_odb_extractor.py code\sclas_offline_diagnostics.py
C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe code\sclas_self_check.py
powershell -ExecutionPolicy Bypass -File .\run_lab_abaqus_smoke.ps1 -SmallSmoke
```

The final Lab-PC SmallSmoke created:

```text
jobs\SCLAS_jobs\small_smoke_20260614_045330
```

Result:

- Abaqus job completed.
- ODB extraction status was `extracted`.
- `result_summary.json.source` was `SCLAS_ABAQUS_ODB_EXTRACTOR`.
- `odb_extraction.rows_written` was `2`.
- `contact_pair_keyword_adjustment.status` was `adjusted`.
- `contact_pair_keyword_adjustment.adjusted_count` was `4`.
- The generated `.inp` contains four
  `*Contact Pair ... type=NODE TO SURFACE` records.
- Searching the final `.dat` for
  `SURFACE TO SURFACE CONTACT APPROACH|NODE TO SURFACE APPROACH` returned
  zero hits.
- The completed solver warning count dropped to:

```text
WITH      5 WARNING MESSAGES ON THE DAT FILE
AND     689 WARNING MESSAGES ON THE MSG FILE
129 WARNINGS ARE FOR NUMERICAL PROBLEMS
```

Remaining non-blocking warning classes are still dominated by armour beam
constraint/contact quality: numerical singularity, overconstraint checks,
unconnected regions, beam curvature, and general-contact/contact-pair overlap.

## Lab Curve V0 Sweep After Contact Adjustment - 2026-06-14 KST

After commit `c40a64c Use node-to-surface for beam contact pairs`, the full
default Curve V0 endpoint sweep was rerun:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_curve_v0_sweep.ps1
```

Runtime was about 14 minutes 48 seconds, below the 20-minute intervention
threshold. The sweep created:

```text
jobs\SCLAS_jobs\curve_v0_sweep_20260614_045750
```

Parent result:

```csv
curvature_1_per_m,moment_kn_m
-0.0079999997979,-0.84404125
-0.00399999989895,-0.4220246875
0,0
0.00399999989895,0.42202409375
0.0079999997979,0.8440385625
```

Parent diagnostics:

```text
source=SCLAS_CURVE_V0_ENDPOINT_SWEEP
rows=5
endpoint_sweep_shape.shape_checks_passed=true
endpoint_sweep_children.all_children_deep_validated=true
endpoint_sweep_children.blocking_log_hits=0
diagnostic_summary.issue_counts={'error': 0, 'warning': 0, 'info': 0}
```

Child jobs:

```text
curve_v0_20260614_045750  factor=-0.1   adjust=adjusted  adjusted_count=4  fallback_hits=0  rows=2
curve_v0_20260614_050108  factor=-0.05  adjust=adjusted  adjusted_count=4  fallback_hits=0  rows=2
curve_v0_20260614_050401  factor=0      adjust=adjusted  adjusted_count=4  fallback_hits=0  rows=2
curve_v0_20260614_050627  factor=0.05   adjust=adjusted  adjusted_count=4  fallback_hits=0  rows=2
curve_v0_20260614_050920  factor=0.1    adjust=adjusted  adjusted_count=4  fallback_hits=0  rows=2
```

For every child:

- Abaqus/Standard completed.
- ODB extraction status was `extracted`.
- `result_summary.json.source` was `SCLAS_ABAQUS_ODB_EXTRACTOR`.
- `odb_extraction.rows_written` was `2`.
- `abaqus_mesh_manifest.json.contact_pair_keyword_adjustment.status` was
  `adjusted`.
- Searching `.dat` for
  `SURFACE TO SURFACE CONTACT APPROACH|NODE TO SURFACE APPROACH` returned
  zero hits.

Remaining completed-child warning taxonomy for the parent sweep:

```text
numerical_singularity=1367
overconstraint_check=605
coupling_or_reference_node_note=60
other_warning=40
increment_cutback_or_excessive_reporting=15
distorted_elements=10
beam_curvature=10
contact_pair_general_contact_overlap=5
unconnected_regions=5
```

The contact fallback warning class was removed from the new sweep. The next
modelling target is therefore not contact-pair formulation fallback, but the
underlying armour beam constraint/contact stability that causes numerical
singularity and overconstraint-check warning volume.

Follow-up diagnostics reporting:

- `code/sclas_offline_diagnostics.py` now exposes the same warning taxonomy on
  ordinary single-job `solver_logs.warning_categories`, not only parent sweep
  child aggregation.
- Latest direct check on `small_smoke_20260614_045330` reported zero diagnostic
  issues and these top single-job warning categories:

```text
numerical_singularity=133
overconstraint_check=77
coupling_or_reference_node_note=12
other_warning=8
increment_cutback_or_excessive_reporting=3
distorted_elements=2
beam_curvature=2
contact_pair_general_contact_overlap=1
unconnected_regions=1
```

## Lab Armour End Coupling Stabilization - 2026-06-14 KST

The next warning bottleneck was the large numerical-singularity and
unconnected-region warning volume from the armour B31 beam layers. The earlier
keyword coupling fallback only included the six solid-equivalent layer end-node
sets. The inner and outer armour beam end nodes were therefore not tied into the
left/right bending reference surfaces, leaving the beam layers weakly connected
during the cyclic bending step.

Implementation:

- `code/abaqus_runner.py` now separates `end_coupling_node_specs` from the
  solid end-face bookkeeping.
- Solid layers still append their end-node labels through the existing
  `append_solid_end_face_spec()` path.
- `InnerArmourHelix` and `OuterArmourHelix` now append their left/right end-node
  labels after B31 mesh generation and contact-region creation.
- The Abaqus 2019 keyword coupling fallback builds the injected left/right
  node-based coupling surfaces from `end_coupling_node_specs`, so the six solid
  layers plus two armour beam layers are all included.
- `code/SCLAS_test/abaqus_runner.py` was synchronized.

Static verification:

```powershell
C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m py_compile code\abaqus_runner.py code\SCLAS_test\abaqus_runner.py code\sclas_odb_extractor.py code\sclas_offline_diagnostics.py code\sclas_self_check.py
C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe code\sclas_self_check.py
```

Both passed. The self-check created:

```text
jobs\SCLAS_jobs\self_check_20260614_130445
jobs\SCLAS_jobs\self_check_endpoint_sweep_20260614_130445
```

Lab-PC SmallSmoke verification:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_lab_abaqus_smoke.ps1 -SmallSmoke
```

SmallSmoke created:

```text
jobs\SCLAS_jobs\small_smoke_20260614_130457
```

Result:

- Abaqus job completed.
- ODB extraction status was `extracted`.
- `result_summary.json.source` was `SCLAS_ABAQUS_ODB_EXTRACTOR`.
- `odb_extraction.rows_written` was `2`.
- `boundary_condition_scaffold.keyword_coupling_fallback.status` was
  `injected`.
- `left_node_set_count=8` and `right_node_set_count=8`, confirming that both
  armour beam layers joined the six solid layers in the endpoint coupling
  fallback.
- Searching the `.dat` file for
  `SURFACE TO SURFACE CONTACT APPROACH|NODE TO SURFACE APPROACH|NUMERICAL SINGULARITY|UNCONNECTED REGIONS`
  returned zero hits.

Single-job warning taxonomy improved from the previous SmallSmoke baseline:

```text
before: numerical_singularity=133, overconstraint_check=77, unconnected_regions=1
after:  numerical_singularity=0,   overconstraint_check=2,  unconnected_regions=0
```

Lab-PC full Curve V0 endpoint sweep:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_curve_v0_sweep.ps1
```

Runtime was about 13 minutes 58 seconds, below the 20-minute intervention
threshold. The sweep created:

```text
jobs\SCLAS_jobs\curve_v0_sweep_20260614_130758
```

Parent result:

```csv
curvature_1_per_m,moment_kn_m
-0.0079999997979,-2.588653
-0.00399999989895,-1.294349625
0,0
0.00399999989895,1.294349
0.0079999997979,2.58865
```

Parent diagnostics:

```text
source=SCLAS_CURVE_V0_ENDPOINT_SWEEP
rows=5
endpoint_sweep_shape.shape_checks_passed=true
endpoint_sweep_children.all_children_deep_validated=true
endpoint_sweep_children.blocking_log_hits=0
diagnostic_summary.issue_counts={'error': 0, 'warning': 0, 'info': 0}
```

Child jobs:

```text
curve_v0_20260614_130758  factor=-0.1   leftSets=8  rightSets=8  rows=2
curve_v0_20260614_131052  factor=-0.05  leftSets=8  rightSets=8  rows=2
curve_v0_20260614_131345  factor=0      leftSets=8  rightSets=8  rows=2
curve_v0_20260614_131611  factor=0.05   leftSets=8  rightSets=8  rows=2
curve_v0_20260614_131902  factor=0.1    leftSets=8  rightSets=8  rows=2
```

For every child:

- Abaqus/Standard completed.
- ODB extraction status was `extracted`.
- `result_summary.json.source` was `SCLAS_ABAQUS_ODB_EXTRACTOR`.
- `odb_extraction.rows_written` was `2`.
- The endpoint coupling fallback injected eight left and eight right component
  node sets.
- Searching `.dat` for the contact-pair fallback, numerical-singularity, and
  unconnected-region patterns returned zero hits.

Remaining completed-child warning taxonomy for the parent sweep:

```text
coupling_or_reference_node_note=60
other_warning=30
increment_cutback_or_excessive_reporting=15
beam_curvature=10
overconstraint_check=10
distorted_elements=10
contact_pair_general_contact_overlap=5
```

Important interpretation:

- The Curve V0 moment baseline changed from about `+/-0.844 kN*m` to about
  `+/-2.589 kN*m` because the armour beams now participate in the end bending
  coupling instead of being weakly connected/free at the endpoints.
- Treat this as a more physical endpoint-coupled v0 baseline, but still not a
  calibrated research hysteresis model.
- The next modelling target is the smaller residual warning set:
  overconstraint checks, contact-pair/general-contact overlap, beam curvature,
  and distorted element warnings. Do not change those until the first concrete
  blocking or clearly reducible warning mechanism is isolated.

## Lab Explicit Contact Pair Cleanup - 2026-06-14 KST

The next reducible warning mechanism was the Abaqus input-processing warning
caused by defining both explicit `*Contact Pair` records and an `ALL EXTERIOR`
general contact interaction. In the generated deck, Abaqus excluded the contact
pair surfaces from the general-contact domain and also warned that the same
surface interaction property was being used by general contact and contact
pairs.

Implementation:

- `code/abaqus_runner.py` now creates explicit contact pair records before the
  optional general-contact scaffold.
- If at least one explicit pair is created, `SCLAS_GeneralContact` is not
  created in the Abaqus model. The manifest records this as
  `contact_interaction_scaffold.status=skipped_explicit_pairs_active` and the
  top-level `contact_interaction_scaffold_status=skipped`.
- The manifest records the created explicit pair names and any skipped pair
  names. The current skipped pair remains `Pair_armour_cross_layer_interaction`
  because both regions are B31 beam-line surfaces.
- This intentionally preserves the four active armour-to-solid contact pairs
  and removes only the overlapping all-exterior general-contact block.
- `code/SCLAS_test/abaqus_runner.py` was synchronized.

Static verification:

```powershell
C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m py_compile code\abaqus_runner.py code\SCLAS_test\abaqus_runner.py code\sclas_odb_extractor.py code\sclas_offline_diagnostics.py code\sclas_self_check.py
C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe code\sclas_self_check.py
```

Both passed. The self-check created:

```text
jobs\SCLAS_jobs\self_check_20260614_132714
jobs\SCLAS_jobs\self_check_endpoint_sweep_20260614_132714
```

Lab-PC SmallSmoke verification:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_lab_abaqus_smoke.ps1 -SmallSmoke
```

SmallSmoke created:

```text
jobs\SCLAS_jobs\small_smoke_20260614_132725
```

Result:

- Abaqus job completed.
- ODB extraction status was `extracted`.
- `result_summary.json.source` was `SCLAS_ABAQUS_ODB_EXTRACTOR`.
- `odb_extraction.rows_written` was `2`.
- `contact_interaction_scaffold_status` was `skipped`.
- The generated `.inp` contained four `*Contact Pair` records and zero
  `*Contact`, `*Contact Inclusions`, or `*Contact Property Assignment` general
  contact records.
- Searching `.dat` for
  `BOTH CONTACT PAIRS AND GENERAL CONTACT|STRICTLY-ENFORCED HARD CONTACT|SURFACE TO SURFACE CONTACT APPROACH|NODE TO SURFACE APPROACH|NUMERICAL SINGULARITY|UNCONNECTED REGIONS`
  returned zero hits.

Lab-PC full Curve V0 endpoint sweep:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_curve_v0_sweep.ps1
```

Runtime was about 2 minutes 42 seconds, below the 20-minute intervention
threshold. The sweep created:

```text
jobs\SCLAS_jobs\curve_v0_sweep_20260614_132815
```

Parent result stayed unchanged from the endpoint-coupled baseline:

```csv
curvature_1_per_m,moment_kn_m
-0.0079999997979,-2.588653
-0.00399999989895,-1.294349625
0,0
0.00399999989895,1.294349
0.0079999997979,2.58865
```

Parent diagnostics:

```text
source=SCLAS_CURVE_V0_ENDPOINT_SWEEP
rows=5
endpoint_sweep_shape.shape_checks_passed=true
endpoint_sweep_children.all_children_deep_validated=true
endpoint_sweep_children.blocking_log_hits=0
diagnostic_summary.issue_counts={'error': 0, 'warning': 0, 'info': 0}
```

Child contact checks:

```text
curve_v0_20260614_132815  factor=-0.1   interaction=skipped  contactBlocks=0  pairBlocks=4  badHits=0  rows=2
curve_v0_20260614_132848  factor=-0.05  interaction=skipped  contactBlocks=0  pairBlocks=4  badHits=0  rows=2
curve_v0_20260614_132921  factor=0      interaction=skipped  contactBlocks=0  pairBlocks=4  badHits=0  rows=2
curve_v0_20260614_132951  factor=0.05   interaction=skipped  contactBlocks=0  pairBlocks=4  badHits=0  rows=2
curve_v0_20260614_133024  factor=0.1    interaction=skipped  contactBlocks=0  pairBlocks=4  badHits=0  rows=2
```

Remaining completed-child warning taxonomy for the parent sweep:

```text
coupling_or_reference_node_note=60
other_warning=25
increment_cutback_or_excessive_reporting=15
overconstraint_check=10
distorted_elements=10
beam_curvature=10
```

The contact-pair/general-contact overlap warning class and the contact-property
penalty-switch warning class are now removed. The next concrete modelling
target is mesh/beam quality: `WarnElemDistorted`, `WarnBeamCurvature1`, and
the beam-tangent curvature warning. The `.msg` files still report zero analysis
warnings and zero numerical-problem warnings, so these are completed-job input
quality warnings rather than current blocking errors.

## Lab Mesh Quality Probe - 2026-06-14 KST

After the contact cleanup, the remaining actual Abaqus input warnings were
investigated:

- `WarnElemDistorted` samples are consistently concentrated in
  `BeddingEquivalent` elements.
- `WarnBeamCurvature1` and `WarnBeamTwist` are tied to the helical B31 armour
  beam elements and Abaqus' beam-normal/default-curvature checks.
- The `.msg` files still report `0 WARNING MESSAGES DURING ANALYSIS` and
  `0 ANALYSIS WARNINGS ARE NUMERICAL PROBLEM MESSAGES`.

A low-risk mesh-control probe was tried locally but not committed:

- The runner temporarily requested `HEX` / `SWEEP` mesh controls for extruded
  circular and annular solids.
- Abaqus accepted the request; the manifest in
  `jobs\SCLAS_jobs\small_smoke_20260614_133415` showed
  `solid_mesh_control_scaffold_status=applied` for all solid components.
- The SmallSmoke still completed and ODB extraction still wrote two rows.
- The warning taxonomy did not improve:

```text
distorted_elements=2
beam_curvature=2
other_warning=5
overconstraint_check=2
```

Because the probe had no stabilizing effect, the code change was reverted and
not committed. Do not retry plain `HEX` / `SWEEP` mesh controls as the next
fix. The next useful mesh-quality task should inspect a real remeshing strategy
for the thin bedding annulus, such as partitioning the annular cross-section,
using a more appropriate thin-layer representation, or changing the scaffold
geometry for bedding after confirming the impact on the endpoint moment curve.

## Diagnostics Warning/Note Split - 2026-06-14 KST

Offline diagnostics now separates real Abaqus warning lines from completed-job
keyword echo and progress notes:

- `warning_categories` now counts only actual warning lines such as
  `***WARNING`.
- `note_categories` counts notable but non-warning lines such as `*coupling`
  keyword echo, `COLLECTING ... OVERCONSTRAINT CHECKS`, and solver summary
  warning-count lines.
- `actual_warning_log_hits` / `actual_warning_match_count` expose the actual
  warning line count.
- `note_log_hits` / `note_match_count` expose the remaining notable note count.
- `code\sclas_self_check.py` now verifies that overconstraint progress lines
  are retained as notes, not counted as warnings.

Verification:

```powershell
C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m py_compile code\abaqus_runner.py code\SCLAS_test\abaqus_runner.py code\sclas_odb_extractor.py code\sclas_offline_diagnostics.py code\sclas_self_check.py
C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe code\sclas_self_check.py
```

Both passed. The self-check created:

```text
jobs\SCLAS_jobs\self_check_20260614_133840
jobs\SCLAS_jobs\self_check_endpoint_sweep_20260614_133840
```

Rechecking the latest real parent sweep:

```text
jobs\SCLAS_jobs\curve_v0_sweep_20260614_132815
```

Result:

```text
rows=5
source=SCLAS_CURVE_V0_ENDPOINT_SWEEP
endpoint_sweep_shape.shape_checks_passed=true
endpoint_sweep_children.all_children_deep_validated=true
endpoint_sweep_children.blocking_log_hits=0
actual_warning_log_hits=15
note_log_hits=115
notable_log_hits=130
```

Actual warning taxonomy is now:

```text
beam_curvature=10
distorted_elements=5
```

Note/progress taxonomy is now:

```text
coupling_or_reference_node_note=60
other_warning=25
increment_cutback_or_excessive_reporting=15
overconstraint_check=10
distorted_elements=5
```

This confirms the next true modelling target is not overconstraint or coupling
failure. It is the actual input-warning pair:

- `BeddingEquivalent` distorted solid elements.
- Armour B31 beam curvature/twist normal checks.

## Mesh/Beam Warning Probe - 2026-06-14 KST

The next modelling-warning pass tested two low-risk hypotheses before making
any persistent runner change.

Beam normal probe:

- Temporarily removed the explicit B31 beam section orientation
  `n1=(0, 0, -1)` from `create_armour_layer()`.
- Ran:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_lab_abaqus_smoke.ps1 -SmallSmoke
```

- Probe job:

```text
jobs\SCLAS_jobs\small_smoke_20260614_134129
```

- Abaqus completed and ODB extraction wrote two rows.
- Actual warning taxonomy was unchanged:

```text
distorted_elements=1
beam_curvature=2
```

- The change was reverted and not committed. The explicit `n1=(0, 0, -1)`
  orientation remains in the runner.

Mesh density probe:

- Kept code unchanged and increased only reduced-smoke mesh parameters:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_lab_abaqus_smoke.ps1 -SmallSmoke -SmallCoreCircumferentialDivisions 16 -SmallArmourCircumferentialDivisions 8
```

- Probe job:

```text
jobs\SCLAS_jobs\small_smoke_20260614_134244
```

- Abaqus completed and ODB extraction wrote two rows.
- Actual warning taxonomy was still unchanged:

```text
distorted_elements=1
beam_curvature=2
```

- Do not treat simple reduced-mesh circumferential refinement as the next fix;
  it did not reduce the remaining warnings.

Diagnostics improvement:

- `code\sclas_offline_diagnostics.py` now adds
  `mesh_quality_warning_details` for single jobs and parent endpoint sweeps.
- The detail records:
  - `warning_sets`
  - `distorted_sample_parts`
  - `distorted_sample_count`
  - `distorted_sample_min_angle`
- Rechecking the latest successful sweep
  `jobs\SCLAS_jobs\curve_v0_sweep_20260614_132815` now reports:

```text
actual_warning_log_hits=15
warning_sets:
  WarnBeamTwist=5
  WarnBeamCurvature1=5
  WarnElemDistorted=5
distorted_sample_parts:
  BEDDINGEQUIVALENT=2500
distorted_sample_min_angle=42.087
```

Interpretation:

- Each CurveV0 child has one `WarnElemDistorted`, one `WarnBeamCurvature1`, and
  one `WarnBeamTwist` actual warning.
- The distorted element table samples point consistently to the thin
  `BeddingEquivalent` annular solid, not a scattered multi-part mesh problem.
- The next real modelling task should be a bedding-specific representation or
  partitioning strategy, or a more targeted B31 helical beam orientation method
  that assigns local radial/tangent-consistent normals rather than simply
  dropping the orientation line.

## Bedding Element Formulation / Smoke Helper Probe - 2026-06-14 KST

The next reduced-risk probe checked whether switching the reduced-smoke solid
element request from the default reduced-integration solid to `C3D8` reduces the
remaining `BeddingEquivalent` distortion warning.

Short-name C3D8 probe:

```text
jobs\SCLAS_jobs\c3d8p_134742
```

- Abaqus completed and ODB extraction wrote two rows.
- `result_summary.json.source` remained `SCLAS_ABAQUS_ODB_EXTRACTOR`.
- Actual warning taxonomy did not improve:

```text
distorted_elements=1
beam_curvature=2
WarnElemDistorted=1
WarnBeamCurvature1=1
WarnBeamTwist=1
distorted_sample_parts:
  BEDDINGEQUIVALENT=500
distorted_sample_min_angle=41.6927
```

Interpretation:

- Do not adopt `C3D8` as the bedding distortion fix. It completed, but the
  distorted bedding sample angle worsened versus the prior `42.087` baseline.
- The next bedding fix should be geometry/partitioning/representation-specific,
  not a simple element-formulation switch.

The first long-name C3D8 probe also exposed a smoke-helper robustness issue:

```text
jobs\SCLAS_jobs\small_smoke_c3d8_20260614_134702
```

The Abaqus runner produced `small_smoke_c3d8_20260614_134702.inp` because
`safe_name(model_name + "_mesh", 32)` can clip the `_mesh` suffix for long
metadata-derived job names. `run_lab_abaqus_smoke.ps1` previously looked only
for `*_mesh.inp` or `*_mes.inp`, so it failed before solver submission even
though a valid `.inp` existed.

Helper fix:

- `run_lab_abaqus_smoke.ps1` now keeps the preferred `*_mesh.inp`/`*_mes.inp`
  lookup, then falls back to the latest `.inp` in the job folder with a yellow
  status message.
- Re-run with `-SkipGeneration` on the long-name probe completed successfully:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_lab_abaqus_smoke.ps1 -JobDir "C:\Users\user\Documents\SCLAS-cable-analysis\jobs\SCLAS_jobs\small_smoke_c3d8_20260614_134702" -SkipGeneration
```

- Abaqus completed and ODB extraction wrote two rows.
- The warning profile matched the short-name C3D8 probe, confirming the helper
  fix only made input-deck discovery more robust and did not change the model.

Post-fallback verification:

- Normal bridge check passed:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_lab_abaqus_smoke.ps1 -SmallSmoke
```

```text
jobs\SCLAS_jobs\small_smoke_20260614_135114
```

- Abaqus completed, ODB extraction status was `extracted`, and
  `odb_extraction.rows_written=2`.
- Latest CurveV0 endpoint sweep also passed:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_curve_v0_sweep.ps1
```

```text
jobs\SCLAS_jobs\curve_v0_sweep_20260614_135200
```

- Parent `result_data.csv` has five data rows:

```text
curvature_1_per_m,moment_kn_m
-0.0079999997979,-2.588653
-0.00399999989895,-1.294349625
0,0
0.00399999989895,1.294349
0.0079999997979,2.58865
```

- Parent `result_summary.json.source` is `SCLAS_CURVE_V0_ENDPOINT_SWEEP`.
- `endpoint_sweep_validation.all_child_jobs_validated=true`.
- Saved parent offline diagnostics report confirms
  `endpoint_sweep_shape.shape_checks_passed=true`,
  `endpoint_sweep_children.all_children_deep_validated=true`, and
  `blocking_log_hits=0`.
- The remaining actual warning profile is unchanged and non-blocking:

```text
WarnElemDistorted=5
WarnBeamCurvature1=5
WarnBeamTwist=5
distorted_sample_parts:
  BEDDINGEQUIVALENT=2500
distorted_sample_min_angle=42.087
```

## Annular Quadrant Mesh Stabilization - 2026-06-14 KST

The next warning-reduction pass first improved offline diagnostics so the
distorted-element warning is no longer summarized only from the first 500 table
rows.

New diagnostics fields:

- `distorted_reported_element_count`
- `distorted_table_parts`
- `distorted_table_row_count`
- `distorted_table_min_angle`

Re-reading the previous stable sweep
`jobs\SCLAS_jobs\curve_v0_sweep_20260614_135200` showed the real pre-fix
distortion profile:

```text
per child distorted_reported_element_count=2025
per child distorted_table_parts:
  BEDDINGEQUIVALENT=1992
  INNERSHEATHEQUIVALENT=33
parent distorted_reported_element_count=10125
```

So the warning was mainly `BeddingEquivalent`, but it was an annular-solid mesh
quality issue rather than a pure bedding-only material/element-formulation
issue.

Implemented stabilization:

- `code\abaqus_runner.py` now enables `mesh.annular_partition_quadrants` by
  default.
- Annular equivalent solids are partitioned by the XZ/YZ datum planes into
  quadrants before meshing.
- Partitioned annular cells request `HEX`/`SWEEP` mesh controls.
- Layer inner/outer contact surfaces now support multiple probe points and a
  radius-based fallback so partitioned cylindrical faces are still collected
  into named surfaces.
- `abaqus_mesh_manifest.json` records `mesh_control_adjustments` and per-surface
  face counts for these named contact surfaces.
- `code\SCLAS_test\abaqus_runner.py` is synchronized with
  `code\abaqus_runner.py`.

The first successful full probe was:

```text
jobs\SCLAS_jobs\annpart4_141324
```

It used `-GenerateOnly` first to confirm:

```text
contact_region_scaffold_status=created
contact_interaction_scaffold_status=skipped
contact_pair_scaffold_status=partial
```

The remaining contact-pair `partial` status is the known skipped B31 beam-beam
cross-layer pair, not a missing annular contact surface. The four beam-to-solid
explicit pairs are created and general contact remains skipped.

Solver/ODB verification for `annpart4_141324`:

```text
Abaqus JOB annpart4_141324_mesh COMPLETED
ODB extraction status=extracted
odb_extraction.rows_written=2
WarnElemDistorted=0
distorted_reported_element_count=0
WarnBeamCurvature1=1
WarnBeamTwist=1
```

Default SmallSmoke after enabling annular quadrant partition:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_lab_abaqus_smoke.ps1 -SmallSmoke
```

```text
jobs\SCLAS_jobs\small_smoke_20260614_141503
```

Result:

```text
Abaqus completed
ODB extraction status=extracted
odb_extraction.rows_written=2
contact_region_scaffold_status=created
contact_interaction_scaffold_status=skipped
WarnElemDistorted=0
actual_warning_match_count=2
warning_sets:
  WarnBeamCurvature1=1
  WarnBeamTwist=1
```

Default CurveV0 endpoint sweep after enabling annular quadrant partition:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_curve_v0_sweep.ps1
```

```text
jobs\SCLAS_jobs\curve_v0_sweep_20260614_141537
```

Parent result rows:

```text
curvature_1_per_m,moment_kn_m
-0.0079999997979,-2.58634625
-0.00399999989895,-1.293202625
0,0
0.00399999989895,1.2932135
0.0079999997979,2.58638975
```

Parent diagnostics:

```text
source=SCLAS_CURVE_V0_ENDPOINT_SWEEP
rows_written=5
endpoint_sweep_validation.all_child_jobs_validated=true
endpoint_sweep_shape.shape_checks_passed=true
endpoint_sweep_children.all_children_deep_validated=true
blocking_log_hits=0
actual_warning_log_hits=10
warning_sets:
  WarnBeamCurvature1=5
  WarnBeamTwist=5
distorted_reported_element_count=0
```

Interpretation:

- The annular quadrant partition is now the stable default for Abaqus mesh
  generation.
- The previous `WarnElemDistorted` class is removed from SmallSmoke and CurveV0.
- The next warning-reduction target is B31 helical beam normal/curvature/twist
  handling, not annular solid distortion.
- Mac-side offline diagnostics now exposes B31-specific warning details under
  `b31_beam_warning_details` for both single Abaqus jobs and CurveV0 sweep
  parents. It separately aggregates `WarnBeamCurvature1` and `WarnBeamTwist`
  and recommends a minimal B31 helix probe when those warnings remain.

## B31 Armour Beam Orientation Stabilization - 2026-06-14 KST

The next Lab-PC pass targeted the remaining completed-solver B31 warning sets:

```text
WarnBeamCurvature1=1 per SmallSmoke
WarnBeamTwist=1 per SmallSmoke
WarnBeamCurvature1=5 and WarnBeamTwist=5 per five-child CurveV0 sweep
```

Tested orientation probes:

- `abaqus_default` / no explicit beam orientation:
  - completed and extracted ODB, but kept both `WarnBeamCurvature1=1` and
    `WarnBeamTwist=1`.
- `radial_segment`:
  - projected a cable-radial normal onto each B31 segment tangent.
  - removed `WarnBeamCurvature1`, but left `WarnBeamTwist=1`.
- `bishop_segment`:
  - uses a discrete parallel-transport frame per helical wire.
  - starts from the radial normal and then minimally rotates the beam normal as
    each segment tangent changes, reducing artificial section twist about the
    beam tangent.
  - removed both `WarnBeamCurvature1` and `WarnBeamTwist` in SmallSmoke and
    CurveV0.

Implemented stabilization:

- `mesh.armour_beam_orientation_mode` now defaults to `bishop_segment`.
- Supported modes are still available for debugging:
  `bishop_segment`, `transport_segment`, `minimum_twist`, `radial_segment`,
  `global_z`/`legacy`, and `abaqus_default`.
- `abaqus_mesh_manifest.json` records `beam_orientation_adjustments` for each
  armour layer, including mode, orientation frame, expected segment count,
  assigned segment count, fallback status, and warnings.
- `code\SCLAS_test\abaqus_runner.py` is synchronized with
  `code\abaqus_runner.py`.

Final default SmallSmoke verification:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_lab_abaqus_smoke.ps1 -SmallSmoke -JobDir "C:\Users\user\Documents\SCLAS-cable-analysis\jobs\SCLAS_jobs\job_20260611_231236_85a1760e"
```

```text
jobs\SCLAS_jobs\small_smoke_20260614_144003
Abaqus JOB small_smoke_20260614_144003_mesh COMPLETED
result_summary.json.source=SCLAS_ABAQUS_ODB_EXTRACTOR
odb_extraction.status=extracted
odb_extraction.rows_written=2
blocking_match_count=0
actual_warning_match_count=0
warning_sets={}
distorted_reported_element_count=0
InnerArmourHelix orientation=created:bishop_segment:880/880
OuterArmourHelix orientation=created:bishop_segment:944/944
```

Final default CurveV0 endpoint sweep verification:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_curve_v0_sweep.ps1
```

```text
jobs\SCLAS_jobs\curve_v0_sweep_20260614_144042
source=SCLAS_CURVE_V0_ENDPOINT_SWEEP
rows_written=5
csv_rows=5
endpoint_sweep_validation.all_child_jobs_validated=true
child_count=5
```

Parent result rows:

```text
curvature_1_per_m,moment_kn_m
-0.0079999997979,-2.58670125
-0.00399999989895,-1.29338025
0,0
0.00399999989895,1.293391125
0.0079999997979,2.58674475
```

All five child jobs:

```text
source=SCLAS_ABAQUS_ODB_EXTRACTOR
odb_extraction.status=extracted
odb_extraction.rows_written=2
blocking_match_count=0
actual_warning_match_count=0
warning_sets={}
distorted_reported_element_count=0
InnerArmourHelix orientation=created:bishop_segment:880/880
OuterArmourHelix orientation=created:bishop_segment:944/944
```

Interpretation:

- The current reduced SmallSmoke and five-factor CurveV0 endpoint sweep now
  complete with no completed-solver actual warning sets.
- The remaining `contact_pair_scaffold_status=partial` is still the known
  skipped B31 beam-beam cross-layer contact pair, not a solver blocker.
- The next backend step should move from bridge/mesh warning stabilization to
  richer Abaqus physics: continuous bending path validation, contact/friction
  refinement, and local ODB field extraction.
- Mac-side GUI result summaries now surface the newer Abaqus quality fields:
  `abaqus_result_quality`, ODB extraction status/rows, CurveV0 endpoint
  validation, warning category counts, mesh warning sets, distorted element
  counts, and beam-orientation manifest summaries. This is display-only and
  does not change the Abaqus runner.

## Continuous CurveV0 Single-Job Path - 2026-06-14 KST

After the endpoint sweep stabilized, the next Lab-PC pass revisited a single
Abaqus job with multiple accepted bending states. Earlier multi-step attempts
were too slow because they used the full GUI curvature. The successful reduced
path scales the GUI `max_curvature_1_per_m` by `0.1`, matching the endpoint
sweep magnitude, then runs:

```text
0 -> +k -> 0 -> -k -> 0
```

New automation:

```text
run_curve_v0_continuous.ps1
```

Default command:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_curve_v0_continuous.ps1
```

What it does:

- Finds the latest GUI `job_*` source unless `-JobDir` is supplied.
- Creates a temporary `continuous_curve_v0_source_...` source job with
  `max_curvature_1_per_m = source.max_curvature_1_per_m * CurveScale`.
- Calls `run_lab_abaqus_smoke.ps1 -CurveV0 -MultiStepSmoke` with
  `-CurveV0CurvatureScale 1.0` so the reduced curvature is not scaled twice.
- Validates that the generated child job has:
  `result_summary.json.source=SCLAS_ABAQUS_ODB_EXTRACTOR`,
  `odb_extraction.status=extracted`, at least five ODB rows, at least five CSV
  rows, and `abaqus_result_quality.curve_class=multi_point_curve_v0`.

The first automated run before the finite-rotation BC cleanup created:

```text
jobs\SCLAS_jobs\curve_v0_20260614_145218
rows_written=5
actual_warning_match_count=1
warning=FINITE ROTATION BOUNDARY CONDITION SPECIFIED IN MULTISTEP THREE-DIMENSIONAL ANALYSIS. TYPE=VELOCITY SHOULD BE USED
```

The runner was then updated so multistep bending uses Abaqus `VelocityBC`
deltas when that API is available. This preserves the same target UR2 path but
removes Abaqus' finite-rotation displacement warning. If `VelocityBC` is not
available, the runner falls back to the previous displacement-target BC and
records that in `boundary_condition_scaffold.optional_warnings`.

Final automated continuous verification:

```text
jobs\SCLAS_jobs\curve_v0_20260614_145420
source=SCLAS_ABAQUS_ODB_EXTRACTOR
status=completed
odb_extraction.status=extracted
odb_extraction.rows_written=5
abaqus_result_quality.curve_class=multi_point_curve_v0
actual_warning_match_count=0
warning_sets={}
b31_warning_sets={}
rotation_bc_type=velocity_delta
target_curvature_1_per_m=0.008
```

Result rows:

```text
curvature_1_per_m,moment_kn_m
0,-0
0.0079999997979,2.58674475
0,-4.57153059542e-08
-0.0079999997979,-2.586701
0,-8.23443464469e-10
```

Interpretation:

- The repository now has three useful Abaqus validation levels:
  fast `SmallSmoke`, five-child endpoint sweep, and a single-job continuous
  CurveV0 path.
- The continuous path is the best current candidate for the first real
  moment-curvature curve, but it still uses the reduced smoke mesh and simplified
  current contact scaffold. Treat it as a candidate curve pending contact/slip
  validation and calibration, not as final paper-grade physics.

## Important Files

```text
code/sclas_remote_gui.py
code/SCLAS_test/sclas_remote_gui.py
code/sclas_remote_gui_final_code.txt
code/abaqus_runner.py
code/SCLAS_test/abaqus_runner.py
run_lab_abaqus_smoke.ps1
run_curve_v0_sweep.ps1
run_curve_v0_continuous.ps1
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

## 2026-06-14 Mac Support Update - Concise Job Summary CLI

Mac-side support added `code/sclas_job_summary.py`, a small no-Abaqus command
that reuses `code/sclas_offline_diagnostics.py` and prints a one-page health
summary for a copied or generated job folder.

Use it before opening the full diagnostics report:

```bash
python code/sclas_job_summary.py --latest
python code/sclas_job_summary.py jobs/SCLAS_jobs/<job_folder>
python code/sclas_job_summary.py jobs/SCLAS_jobs/<job_folder> --json
```

It reports the current health label, source/status, curve class, CSV/ODB rows,
endpoint sweep validation, actual warning counts, mesh distortion counts, B31
warning sets, beam-orientation manifest status, and the same recommended next
action used by offline diagnostics.

## 2026-06-14 Mac Support Update - Continuous CurveV0 Diagnostics

Mac-side diagnostics now recognize
`abaqus_result_quality.curve_class=multi_point_curve_v0` jobs from
`run_curve_v0_continuous.ps1`.

`code/sclas_offline_diagnostics.py` adds `continuous_curve_v0_shape` with:

- numeric row count and numeric-format status
- positive/negative curvature branch detection
- return-to-zero row count
- moment-curvature sign consistency
- odd-symmetry relative error
- max absolute curvature and moment
- `shape_checks_passed`

`code/sclas_job_summary.py` and the GUI Diagnose selected panel surface the
same continuous CurveV0 shape fields. `code/sclas_self_check.py` now creates a
synthetic continuous CurveV0 ODB-style job and verifies this path.

## 2026-06-14 Mac Support Update - CurveV0 Comparison CLI

Mac-side support added `code/sclas_curve_compare.py`.

Default command:

```bash
python code/sclas_curve_compare.py
```

The command finds the latest endpoint sweep and latest continuous
`multi_point_curve_v0` job under `jobs/SCLAS_jobs`, then compares:

- common absolute curvature
- positive and negative branch moments at that curvature
- relative branch deltas
- continuous/endpoint peak moment ratio
- row counts, max curvature, max moment, and odd-symmetry indicators

Use explicit folders when comparing a specific pair:

```bash
python code/sclas_curve_compare.py \
  --endpoint jobs/SCLAS_jobs/<endpoint_sweep_folder> \
  --continuous jobs/SCLAS_jobs/<continuous_curve_folder>
```

`code/sclas_self_check.py` verifies this path with synthetic endpoint and
continuous CurveV0 jobs and expects the intentionally different moment scale to
be classified as `review`.

## 2026-06-14 Mac Support Update - GUI CurveV0 Compare Button

The Analysis tab now exposes the comparison path directly in the GUI. In
`Recent Jobs`, click `Compare CurveV0` to find the latest endpoint sweep and
latest continuous `multi_point_curve_v0` folder under the configured local job
root, run the same comparison as `code/sclas_curve_compare.py`, and print the
human-readable comparison report in the result summary panel.

The button reports `aligned`, `review`, or `blocked` through the result badge
and logs the peak moment ratio for quick triage.

The same button now also updates the graph: it loads the endpoint sweep as the
primary curve and overlays the continuous CurveV0 result as a dashed comparison
curve. This makes the moment-scale mismatch visible immediately instead of only
reporting it in text.

The plot now includes a legend. The primary result appears as `Primary`, and
the automatic continuous overlay appears as `Continuous CurveV0`, so the
comparison plot is readable without relying only on color.

`code/sclas_curve_compare.py` also supports `--save-report` and
`--save-markdown`. The GUI `Compare CurveV0` action now saves
`curve_v0_comparison_report.json` and `curve_v0_comparison_report.md` into the
continuous CurveV0 job folder before showing the report in the summary panel.
`code/sclas_job_summary.py` now reads that saved JSON report and surfaces the
comparison status, peak moment ratio, branch deltas, warning count, and next
action in concise job summaries.

Verification on Mac:

```bash
../90_env/venv/bin/python -m py_compile code/sclas_job_summary.py code/sclas_self_check.py code/sclas_offline_diagnostics.py
../90_env/venv/bin/python code/sclas_self_check.py
../90_env/venv/bin/python code/sclas_job_summary.py --latest
```

## 2026-06-14 Windows Abaqus Update - ODB Local Field Summary

Windows lab-PC work added a conservative local-field ODB post-processing layer
without changing the narrow `result_data.csv` contract.

Changed code:

- `code/sclas_odb_extractor.py` now writes
  `local_field_summary` inside `odb_extraction_summary.json` and mirrors it to
  `result_summary.json.odb_local_field_summary`.
- The extractor inventories available ODB field outputs and summarizes
  aggregate scalar metrics for `S`, `CPRESS`, `COPEN`, `CSLIP1`, `CSLIP2`,
  `CSHEAR1`, and `CSHEAR2` when present.
- Abaqus interface-qualified contact output keys such as
  `CPRESS   ASSEMBLY_.../ASSEMBLY_...` are matched by prefix, not exact name.
- `code/sclas_offline_diagnostics.py` now reports local field digests for
  single jobs and aggregates them across endpoint-sweep child jobs.
- `code/sclas_job_summary.py` prints the same local field inventory and key
  metrics in the concise one-page summary.

Validation on Windows:

```powershell
python -m py_compile code\abaqus_runner.py code\SCLAS_test\abaqus_runner.py code\sclas_odb_extractor.py code\sclas_offline_diagnostics.py code\sclas_job_summary.py
python code\sclas_self_check.py
powershell -ExecutionPolicy Bypass -File .\run_lab_abaqus_smoke.ps1 -SmallSmoke
powershell -ExecutionPolicy Bypass -File .\run_curve_v0_sweep.ps1
powershell -ExecutionPolicy Bypass -File .\run_curve_v0_continuous.ps1
```

Fresh Windows job folders:

- SmallSmoke: `jobs\SCLAS_jobs\small_smoke_20260614_150938`
  - Abaqus job completed.
  - `odb_extraction.status=extracted`.
  - `odb_extraction.rows_written=2`.
  - `source=SCLAS_ABAQUS_ODB_EXTRACTOR`.
  - `actual_warning_match_count=0`, blocking log hits `0`.
  - Local fields present: `S`, `CPRESS`, `COPEN`, `CSLIP1`, `CSLIP2`,
    `CSHEAR1`, `CSHEAR2`; `CSTATUS` missing.
- Endpoint sweep: `jobs\SCLAS_jobs\curve_v0_sweep_20260614_151023`
  - Parent `result_data.csv` has five numeric rows.
  - Parent `source=SCLAS_CURVE_V0_ENDPOINT_SWEEP`.
  - `endpoint_sweep_validation.all_child_jobs_validated=true`.
  - Offline diagnostics deep-validated all five children.
  - Child aggregate local fields present in 5/5 children for `S`, `CPRESS`,
    `COPEN`, `CSLIP1`, `CSLIP2`, `CSHEAR1`, and `CSHEAR2`.
  - Aggregate metrics: `stress_mises_max=6.312607765197754`,
    `contact_pressure_max=0.0`, `slip_abs_max=0.0`,
    `contact_opening_abs_max=2.5802268981933594`.
  - Actual warning hits `0`, blocking hits `0`.
- Continuous CurveV0: `jobs\SCLAS_jobs\curve_v0_20260614_151349`
  - `odb_extraction.status=extracted`.
  - `odb_extraction.rows_written=5`.
  - `abaqus_result_quality.curve_class=multi_point_curve_v0`.
  - Local fields present: `S`, `CPRESS`, `COPEN`, `CSLIP1`, `CSLIP2`,
    `CSHEAR1`, `CSHEAR2`; `CSTATUS` missing.
  - Metrics: `stress_mises_max=6.312607765197754`,
    `contact_pressure_max=0.0`, `slip_abs_max=0.0`,
    `contact_opening_abs_max=2.580226182937622`.
  - Actual warning hits `0`, blocking hits `0`.

Interpretation:

- The Abaqus bridge and CurveV0 endpoint/continuous validation remain stable.
- ODB contact/stress fields are available and now summarized, but the current
  reduced contact scaffold reports zero contact pressure and zero slip in these
  runs. Treat this as a diagnostic signal, not calibrated contact physics.
- Phase 4 is only partially implemented: aggregate local field metrics exist;
  per-interface ranges, loop energy, contact status interpretation, and
  fatigue/calibration summaries are still open.

## 2026-06-14 Windows Abaqus Update - Curve Scalars and Per-Output Digests

Windows lab-PC work extended the ODB/result diagnostics without changing the
CSV contract:

- `code/sclas_odb_extractor.py` now computes `curve_summary` for ODB-extracted
  rows and mirrors it into `result_summary.json`.
- `curve_summary` records row count, min/max/max-absolute curvature, min/max/
  max-absolute moment, curvature span, moment span, and a trapezoidal
  `loop_energy_proxy_kn`.
- Local ODB field summaries now keep `per_output` stats for interface-qualified
  Abaqus outputs such as `CPRESS   surface/pair`, `COPEN`, `CSLIP*`, and
  `CSHEAR*`.
- `code/sclas_offline_diagnostics.py` and `code/sclas_job_summary.py` now show
  top pressure/opening/slip/shear/stress outputs for single jobs and endpoint
  sweep child-job aggregates.

Fresh Windows validation after this update:

- SmallSmoke: `jobs\SCLAS_jobs\small_smoke_20260614_152436`
  - Abaqus job completed.
  - `source=SCLAS_ABAQUS_ODB_EXTRACTOR`.
  - `odb_extraction.status=extracted`.
  - `odb_extraction.rows_written=2`.
  - Actual warning hits `0`, blocking hits `0`.
- Endpoint sweep: `jobs\SCLAS_jobs\curve_v0_sweep_20260614_152520`
  - Parent `result_data.csv` has five numeric rows.
  - Parent `source=SCLAS_CURVE_V0_ENDPOINT_SWEEP`.
  - `endpoint_sweep_validation.all_child_jobs_validated=true`.
  - Offline diagnostics deep-validated all five child jobs.
  - Shape checks passed with monotonic endpoint curvature/moment and odd
    symmetry relative error about `1.68e-05`.
  - Curve scalars: max `|kappa|=0.0079999997979`, max `|M|=2.58674475`,
    moment span `5.173446`, loop-energy proxy about `1.305e-07`.
  - Aggregate ODB local metrics: `stress_mises_max=6.312607765197754`,
    `contact_pressure_max=0.0`, `slip_abs_max=0.0`,
    `contact_opening_abs_max=2.5802268981933594`.
  - Actual warning hits `0`, blocking hits `0`.
- Continuous CurveV0: `jobs\SCLAS_jobs\curve_v0_20260614_152837`
  - `source=SCLAS_ABAQUS_ODB_EXTRACTOR`.
  - `odb_extraction.status=extracted`.
  - `odb_extraction.rows_written=5`.
  - `abaqus_result_quality.curve_class=multi_point_curve_v0`.
  - Continuous shape checks passed with symmetry error about `1.69e-05`.
  - Curve scalars: max `|kappa|=0.007999999797903001`,
    max `|M|=2.58674475`, moment span `5.173445749999999`,
    loop-energy proxy about `3.62e-10`.
  - Local fields present: `S`, `CPRESS`, `COPEN`, `CSLIP1`, `CSLIP2`,
    `CSHEAR1`, `CSHEAR2`; `CSTATUS` missing.
  - Top opening output was the inner-armour / inner-sheath outer-surface
    interface, around `2.580226182937622`.
  - `contact_pressure_max=0.0` and `slip_abs_max=0.0`, so the current reduced
    scaffold still has detectable contact outputs but no calibrated closed
    contact pressure or slip response.
  - Actual warning hits `0`, blocking hits `0`.

Interpretation:

- The Abaqus bridge, endpoint CurveV0 sweep, and continuous CurveV0 path remain
  stable after the richer diagnostics update.
- There is no current blocking solver/extraction error.
- The first physics blocker is now contact calibration/closure: contact output
  channels exist, but the reduced scaffold reports zero pressure and zero slip.
  The next backend work should make the contact pairs physically close and
  produce nonzero `CPRESS`/slip where expected before claiming paper-grade
  stick-slip behavior.

## 2026-06-14 Windows Abaqus Update - Contact Clearance Diagnostics

Windows lab-PC work added an explicit initial-contact clearance diagnostic for
the Abaqus mesh/contact scaffold:

- `code/abaqus_runner.py` now computes
  `contact_initial_clearance_summary` in `abaqus_mesh_manifest.json`.
- Each created beam-wire / solid-surface contact pair records radial side,
  beam contact radius, solid surface radius, initial clearance, initial
  overclosure, and state (`gapped`, `touching`, or `overclosed`).
- `code/sclas_offline_diagnostics.py` raises a warning when residual contact
  pressure is declared but the scaffold has no initial overclosure/preload.
- `code/sclas_job_summary.py` prints the clearance/preload status in the
  concise health summary.

Fresh Windows validation after this update:

- SmallSmoke: `jobs\SCLAS_jobs\small_smoke_20260614_153845`
  - Abaqus job completed.
  - ODB extraction status `extracted`, rows `2`.
  - `source=SCLAS_ABAQUS_ODB_EXTRACTOR`.
  - Actual warning hits `0`, blocking hits `0`.
  - Contact clearance: checked pairs `4`, gapped `2`, touching `2`,
    overclosed `0`, min gap `0.0 mm`, max gap `0.5 mm`.
  - Residual contact pressure is `0.3 MPa`, but preload status is
    `not_applied`.
- Endpoint sweep: `jobs\SCLAS_jobs\curve_v0_sweep_20260614_153932`
  - Parent `result_data.csv` has five numeric rows.
  - Parent `source=SCLAS_CURVE_V0_ENDPOINT_SWEEP`.
  - `endpoint_sweep_validation.all_child_jobs_validated=true`.
  - Offline diagnostics deep-validated all five children.
  - Shape checks passed with odd-symmetry relative error about `1.68e-05`.
  - Aggregate ODB fields remain present in 5/5 child jobs, but
    `contact_pressure_max=0.0` and `slip_abs_max=0.0`.
- Continuous CurveV0: `jobs\SCLAS_jobs\curve_v0_20260614_154312`
  - Abaqus job completed.
  - ODB extraction status `extracted`, rows `5`.
  - `abaqus_result_quality.curve_class=multi_point_curve_v0`.
  - Continuous shape checks passed with symmetry error about `1.69e-05`.
  - Contact clearance: checked pairs `4`, gapped `2`, touching `2`,
    overclosed `0`, min gap `0.0 mm`, max gap `0.5 mm`.
  - `contact_pressure_max=0.0`, `slip_abs_max=0.0`,
    `contact_opening_abs_max=2.580226182937622`.
  - Recommended next action now correctly identifies the first contact-physics
    blocker: residual pressure/preload is not being applied.

Interpretation:

- The bridge, endpoint sweep, and continuous CurveV0 path remain stable after
  the clearance diagnostics update.
- There is still no solver/extraction blocking error.
- The next modelling fix should add a small, controlled Abaqus
  shrink/interference preload or a reduced-geometry closure option so residual
  pressure can produce nonzero `CPRESS` before contact/slip calibration.

## Next Recommended Tasks

1. Preserve the stable Lab-PC validation loop:
   `run_lab_abaqus_smoke.ps1 -SmallSmoke` for bridge health, then
   `run_curve_v0_sweep.ps1` for the five-factor endpoint sweep, and
   `run_curve_v0_continuous.ps1` for the single-job multi-point curve.
2. If any Abaqus run exceeds 20 minutes without visible progress, stop waiting,
   record it as a long-running case, inspect current logs, and retry with fewer
   factors or a reduced mesh.
3. Keep the GUI/backend result contract stable:
   - `input_data.json` as backend input
   - `result_data.csv` with `curvature_1_per_m,moment_kn_m`
   - `result_summary.json` for optional metrics
4. If completed-solver warning classes reappear, isolate the first concrete
   mechanism in `.dat`/`.msg`/manifest data before changing the model. The
   current reduced SmallSmoke and CurveV0 baseline has
   `actual_warning_match_count=0`.
5. Add true periodic boundary equations or a documented equivalent-cell
   approximation.
6. Extend the new ODB local-field summaries from aggregate maxima to
   full per-interface contact/slip/stress ranges, contact status, and
   fatigue-oriented metrics.
7. Implement and validate a small contact preload/closure path:
   start with a single reduced CurveV0 factor or SmallSmoke, avoid runs longer
   than 20 minutes without log progress, and only then rerun the full endpoint
   sweep.
8. After each meaningful task, update this file, commit, and push only code/docs
   changes, never generated Abaqus job artifacts.

## 2026-06-14 Mac Support Update - Final Roadmap and Status Dashboard

Mac-side completion ownership is now documented in
`docs/HELIX_FINAL_COMPLETION_ROADMAP.md`.

New status command:

```bash
python code/sclas_job_index.py
python code/sclas_job_index.py --save-report --save-markdown
python code/sclas_project_status.py
python code/sclas_project_status.py --json
python code/sclas_project_status.py --save-report --save-markdown
python code/sclas_handoff_snapshot.py --save-report --save-markdown
python code/sclas_next_prompt.py --save
python code/sclas_acceptance_gate.py --save-report --save-markdown
./run_next_prompt.sh
```

Latest-job commands now exclude synthetic `self_check*` folders by default.
Use `--include-self-check` only when validating the synthetic fixtures
themselves.

It summarizes:

- recent real `job_*` runs through `sclas_job_index.py`
- a one-file handoff snapshot with git state, best job, status, acceptance
  gate, and next action
- `NEXT_CODEX_PROMPT.md`, a ready-made prompt for the next Codex session
  generated directly by `run_next_prompt.sh` or `run_next_prompt.bat`
- an acceptance gate that separates completed Abaqus output from research-ready
  contact/CurveV0 evidence and is now embedded in the handoff snapshot/prompt
- latest job health/source/curve class
- latest endpoint-vs-continuous CurveV0 comparison status
- contact preload state, CPRESS max, and slip max
- completion flags for GUI contract, CurveV0 comparison, contact closure, and
  ODB local fields
- the next recommended action

`code/sclas_self_check.py` now verifies this status command. The current
expected top blocker remains contact preload/closure until the remote Abaqus
side produces nonzero CPRESS/slip under the declared residual pressure.

The Analysis tab now has a `Project Status` button in the Recent Jobs panel.
It runs the same project status dashboard and writes the human-readable status
and next action into the summary panel. It also saves
`project_status_report.json` and `project_status_report.md` into the latest job
folder so another Codex session can read the same handoff snapshot. The same
Recent Jobs panel now also has an `Open folder` button for opening the selected
job folder in Finder or Windows Explorer, plus a `Job Index` button for saving
and displaying a recent-job inventory directly in the GUI. Use `Load best` to
load the highest-readiness candidate selected by that index. Use `Handoff` to
save and display `handoff_snapshot.json` and `handoff_snapshot.md` before
switching computers or Codex sessions.

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
Abaqus validation loop from the latest GitHub commit. Use
python code/sclas_job_summary.py --latest for a concise health check, then use
code/sclas_offline_diagnostics.py when deeper .dat/.msg/log context is needed.
Continue preparing code/abaqus_runner.py for real Abaqus contact, periodic
boundary conditions, cyclic bending, job submission, and ODB result extraction.
```
