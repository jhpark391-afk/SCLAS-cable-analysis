# Abaqus Backend Implementation Plan

This plan starts from the current `code/abaqus_runner.py` scaffold and preserves
the GUI contract:

```csv
curvature_1_per_m,moment_kn_m
```

The GUI remains useful as long as every backend iteration writes
`result_data.csv`; richer research metrics should go to `result_summary.json`.

## Current backend state

- Normal Python path:
  - reads `input_data.json`
  - writes placeholder `result_data.csv`
  - writes `result_summary.json`
  - writes `abaqus_mesh_manifest.json`
- Abaqus/CAE path:
  - creates first-pass core/sheath solids and helical armour beam paths
  - writes `.cae` and `.inp` mesh scaffold when Abaqus APIs are available
  - still writes the placeholder result curve

## Verified Lab-PC baseline

As of 2026-06-14, the Lab PC has verified a stable end-to-end Abaqus smoke
bridge:

```text
input_data.json -> Abaqus/CAE noGUI .inp/.cae -> Abaqus/Standard .odb -> ODB extractor -> result_data.csv/result_summary.json
```

The stable smoke job is intentionally small and fast. It writes a two-row ODB
result (`curve_class=two_point_odb_smoke`) and is useful for checking that the
bridge, licenses, coupling keyword fallback, ODB access, and GUI CSV contract
still work.

Do not treat the two-row smoke as a research moment-curvature curve. Do not
spend interactive Lab-PC time trying to force the small smoke to emit more
frames. Multi-point curves now use separate explicit v0 helpers.

`result_summary.json` should distinguish result quality:

- `two_point_odb_smoke`: bridge smoke only, not a research curve.
- `multi_point_curve_v0`: candidate Abaqus curve, requires shape/contact
  validation before research use.
- `odb_extraction_failed` or `too_few_odb_rows`: extraction/debug state.

## Phase 3A: Real curve v0 design

The next backend task is a separate `real moment-curvature curve v0`, not an
extension of the fast smoke test.

Design constraints:

- Keep default `-SmallSmoke` fast and two-row-capable.
- Do not force Abaqus solver increments just to create output frames.
- Use a deliberate load path that creates meaningful accepted solution states.
- Keep the first implementation smaller than the full research model.
- Record the result quality in `result_summary.json.abaqus_result_quality`.

Recommended v0 approach:

1. Add an explicit curve-v0 mode separate from `-SmallSmoke`.
2. Start with a reduced geometry/mesh and a low-cost bending path.
3. Use a limited sequence of target curvatures, for example:

   ```text
   0 -> +kmax -> +0.5kmax -> 0 -> -0.5kmax -> -kmax -> 0
   ```

4. Keep Abaqus increment control automatic at first.
5. Extract right-reference-point `UR2` / `RM2` across all accepted steps.
6. Promote the result to `multi_point_curve_v0` only if at least five valid
   ODB rows are written and the solver completes.
7. After curve-v0 works, add contact pressure/slip summaries to JSON rather
   than widening `result_data.csv`.

Endpoint-sweep command shape:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_curve_v0_sweep.ps1 `
  -JobDir "C:\Users\user\Documents\SCLAS-cable-analysis\jobs\SCLAS_jobs\job_20260611_231236_85a1760e" `
  -CurveFactors -0.1,-0.05,0,0.05,0.1
```

Curve-v0 now uses an endpoint sweep. Each point is a separate, reduced,
single-step Abaqus solve with no cyclic amplitude and no forced solver
increments. The sweep helper aggregates the final ODB endpoint from each child
job into one parent `curve_v0_sweep_.../result_data.csv`.

The parent sweep must only aggregate validated child jobs. Each child must have
`result_summary.json.source=SCLAS_ABAQUS_ODB_EXTRACTOR`,
`odb_extraction.status=extracted`, and at least two extracted ODB rows. If any
child fails this check, stop the sweep rather than mixing placeholder data into
the curve.

Default factors:

```text
-0.1*kmax, -0.05*kmax, 0, +0.05*kmax, +0.1*kmax
```

This is robust because each point follows the same stable single-step pattern
as the smoke baseline. It is useful for checking monotonic endpoint shape and
for comparing child-job health.

Continuous single-job command shape:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_curve_v0_continuous.ps1 `
  -JobDir "C:\Users\user\Documents\SCLAS-cable-analysis\jobs\SCLAS_jobs\job_20260611_231236_85a1760e" `
  -CurveScale 0.1 `
  -PathFactors 1,0,-1,0
```

The continuous helper creates a temporary source job with
`max_curvature_1_per_m = source.max_curvature_1_per_m * CurveScale`, then runs a
reduced multi-step `-CurveV0 -MultiStepSmoke` child with automatic solver
increment control. The current default path gives:

```text
0 -> +k -> 0 -> -k -> 0
```

As of 2026-06-14, the Lab PC verified
`jobs\SCLAS_jobs\curve_v0_20260614_145420`:

```text
odb_extraction.status=extracted
odb_extraction.rows_written=5
abaqus_result_quality.curve_class=multi_point_curve_v0
actual_warning_match_count=0
rotation_bc_type=velocity_delta
```

The `velocity_delta` multistep boundary condition is important: it uses Abaqus
`VelocityBC` deltas for finite rotations and avoids the multistep finite
rotation warning produced by displacement-target BC updates. If Abaqus exposes
no `VelocityBC` API, the runner falls back to displacement targets and records
that in the boundary-condition scaffold.

The continuous path is now the preferred candidate for the first single-job
moment-curvature curve. It still uses the reduced smoke mesh and simplified
contact scaffold, so validate contact/slip fields and calibration before
treating it as paper-grade physics.

## Phase 1: Mesh scaffold verification

1. Run a GUI-exported job in Abaqus:

   ```bat
   abaqus cae noGUI=abaqus_runner.py -- input_data.json
   ```

2. Open `sclas_mesh_model.cae`.
3. Check:
   - core positions and radii
   - inner and outer armour center radii
   - helical hand/direction of each armour layer
   - axial seed count from `mesh.axial_divisions`
   - circumferential seed counts from GUI mesh settings

Acceptance:
- `.cae` and `.inp` files open without Abaqus errors.
- `abaqus_mesh_manifest.json` lists all expected components.

## Phase 2: Contact and friction

Start from `numerical_model.contact_interfaces` in `input_data.json`.

Initial contact pairs:
- inner armour to inner sheath
- inner armour to bedding
- outer armour to bedding
- outer armour to outer sheath
- cross-layer armour interaction, if represented explicitly

Contact settings:
- normal behavior: penalty or augmented Lagrange
- tangential behavior: regularized Coulomb
- friction coefficient: `analysis_conditions.friction_coefficient`
- residual pressure: `analysis_conditions.residual_contact_pressure_mpa`
- regularization: `analysis_conditions.contact_regularization_beta`

Acceptance:
- write contact status and any convergence warnings into
  `result_summary.json.backend_readiness.contact_friction`
- include the exact friction/contact parameters used

## Phase 3: Cyclic bending load case

1. Define a cyclic curvature path using
   `analysis_conditions.max_curvature_1_per_m` and
   `analysis_conditions.loading_cycles`.
2. Apply end rotations/displacements that reproduce the requested curvature
   over `analysis_conditions.effective_length_mm`.
3. Submit the Abaqus job.
4. Extract reaction moment and curvature history.

Acceptance:
- `result_data.csv` contains the ODB-extracted bending loop.
- `result_summary.json.source` changes from placeholder/proxy wording to an
  Abaqus solve source.
- `backend_readiness.bending_stick_slip.status` is updated to `abaqus_solved`
  or a more specific status.

## Phase 4: ODB post-processing

Extract and report:
- peak absolute bending moment
- minimum and maximum moment
- loop energy proxy
- stick/slip transition indicators, if available
- contact pressure range by interface
- slip displacement range by interface
- convergence warnings and failed increments

Keep the CSV narrow. Put extra arrays or scalar metrics in JSON unless the GUI
explicitly needs a new plot.

## Phase 5: Coupled studies

Add separate routines after bending is stable:

1. Torsion:
   - use `analysis_conditions.max_twist_rad_per_m`
   - report torsional stiffness in `result_summary.json`
2. Tension-bending:
   - use `analysis_conditions.max_axial_strain`
   - sweep axial preload before bending
3. Pressure/compression:
   - use `analysis_conditions.hydrostatic_pressure_mpa`
   - use `analysis_conditions.radial_compression_ratio`
   - report pressure softening and bird-caging risk

## Phase 6: GUI promotion criteria

Only add new GUI plots when the backend has stable output for them.

Good candidates:
- contact pressure vs curvature
- slip displacement vs curvature
- torsion moment vs twist
- axial force vs axial strain
- pressure sweep summary

Do not overload `result_data.csv`; create additional CSV files only when a new
plot genuinely needs a vector result.
