# HELIX Final Completion Roadmap

This roadmap separates what can be completed on the Mac/home Codex side from
what must be validated on the remote Windows Abaqus machine.

## Completion Definition

HELIX is considered project-complete when the workflow below is stable,
repeatable, and documented:

```text
GUI inputs
-> reproducible job package
-> Abaqus model generation
-> Abaqus solve
-> ODB extraction
-> result_data.csv / result_summary.json
-> diagnostics and comparison reports
-> GUI visualization
-> research-ready interpretation notes
```

## Mac/Home Codex Ownership

These areas can be pushed forward without running Abaqus locally:

1. GUI workflow completion
   - Keep `code/sclas_remote_gui.py`,
     `code/SCLAS_test/sclas_remote_gui.py`, and
     `code/sclas_remote_gui_final_code.txt` synchronized.
   - Improve Analysis tab result loading, CurveV0 comparison, plot readability,
     language toggle behavior, export actions, and responsive layout.
   - Keep GUI smoke tests passing.

2. Result diagnostics and comparison tooling
   - Maintain `code/sclas_offline_diagnostics.py`.
   - Maintain `code/sclas_job_summary.py`.
   - Maintain `code/sclas_curve_compare.py`.
   - Add new checks whenever the remote Abaqus side produces new fields,
     warnings, or failure modes.

3. Project status automation
   - Maintain `code/sclas_session_brief.py` and `run_session_brief.sh`/`.bat` as
     the one-page startup command for git sync, latest job health, result intake,
     acceptance gates, and next recommended action.
   - Keep `code/sclas_project_status.py` aligned with the acceptance gate for
     contact preload/closure and required ODB local-field readiness.
   - Keep this status command included in `run_self_check.bat` coverage through
     `code/sclas_self_check.py`.

4. Documentation and handoff
   - Keep `CURRENT_HANDOFF.md` current.
   - Keep `README_SCLAS_WORKFLOW.md` current.
   - Keep backend handoff docs aligned with the actual JSON/result contract.
   - Produce prompts for home/remote Codex sessions when needed.

5. Regression protection
   - Keep synthetic contract tests in `code/sclas_self_check.py`.
   - Add synthetic jobs for every important result class:
     FAST preview, SmallSmoke, endpoint sweep, continuous CurveV0, contact
     preload/closure, and local ODB field outputs.
   - Keep a positive research-ready fixture that proves nonzero CPRESS/slip,
     required ODB local fields, aligned CurveV0 comparison, result intake, and
     the acceptance gate can all reach the ready/accepted path.
   - Ensure py_compile, self-check, curve comparison, and GUI smoke stay green.

6. Research interpretation support
   - Translate Abaqus output fields into engineering metrics:
     contact pressure, slip, opening, stress, loop energy, symmetry, stiffness,
     and fatigue-oriented summaries.
   - Keep literature-mapping notes explicit about what is implemented and what
     is still a proxy.

## Remote Windows/Abaqus Ownership

These require the remote Abaqus installation:

1. Real Abaqus solver execution.
2. Contact preload or closure implementation.
3. Nonzero `CPRESS` and slip validation.
4. Periodic boundary or equivalent-cell validation.
5. Contact/friction calibration against literature or measured targets.
6. Longer or denser production runs after reduced runs are stable.

Mac/Home Codex should not pretend these are complete until remote job folders
prove them through ODB extraction and diagnostics.

## Current Main Physics Blocker

The current stable Abaqus bridge can generate:

- SmallSmoke two-row ODB results.
- Five-factor endpoint sweep results.
- Continuous multi-point CurveV0 results.
- ODB local-field inventories.
- Contact clearance/preload diagnostics.

The first unresolved physics blocker is contact closure/preload:

- Contact output channels exist.
- `contact_pressure_max` is currently zero in the reduced scaffold.
- `slip_abs_max` is currently zero in the reduced scaffold.
- Residual contact pressure is declared but not yet physically applied as a
  closed/preloaded contact state.

## Next Priority Order

1. Preserve the stable validation loop.
2. Add project status automation.
3. Make contact preload/closure visible in diagnostics and GUI as soon as the
   remote side produces new manifest or ODB fields.
4. Compare endpoint and continuous CurveV0 after each remote change.
5. Promote nonzero contact pressure/slip into research metrics.
6. Add periodic/equivalent-cell status checks.
7. Add calibration-report templates.
8. Freeze the final result contract and produce the final user workflow.

## Daily Working Rule

Before any change:

```bash
git pull --ff-only
git status --short --branch
```

After any meaningful change:

```bash
python -m py_compile code/sclas_remote_gui.py code/SCLAS_test/sclas_remote_gui.py code/sclas_self_check.py
python code/sclas_self_check.py
```

If the GUI changed, also run the GUI smoke test.

Never commit generated `jobs/SCLAS_jobs/*` folders.
