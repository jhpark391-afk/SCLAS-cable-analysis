# AGENTS.md

This repository is the HELIX / SCLAS submarine cable analysis project.

HELIX = Helical Element Localised Interaction eXamination.

## First Steps

Every Codex session on this repository should start by reading:

1. `docs/internal_handoff/CURRENT_HANDOFF_KR.md` (or `docs/internal_handoff/CURRENT_HANDOFF.md`)
2. `docs/guides/README_SCLAS_WORKFLOW.md`
3. `docs/guides/README_LITERATURE_NOTES.md`

Then run:

```bash
git status --short --branch
```

If the local checkout is behind the remote, pull before editing unless the user
explicitly asks to inspect the old state.

## Main Files

Use these as the main project surfaces:

- GUI source: `code/sclas_remote_gui.py`
- Abaqus backend bridge: `code/abaqus_runner.py`
- Backend handoff: `docs/HELIX_BACKEND_HANDOFF_BOGWANG_KR.md`
- Literature notes: `docs/guides/README_LITERATURE_NOTES.md`

Only edit the source code under the `code/` folder. Do not keep duplicate copies.

## Verification

After GUI or backend edits, run:

```bash
python code/sclas_self_check.py
```

On macOS, the project normally uses:

```bash
../90_env/venv/bin/python
```

On Windows, prefer:

```bat
scripts/run_self_check.bat
```

## Git Handoff Rules

This project is shared between the Mac Codex and the home Windows Codex through
GitHub. Codex instances do not share local terminal state, chat history, running
processes, virtual environments, or uncommitted files.

Use this rhythm:

```bash
git pull
git status --short --branch
# work
# verify (scripts/run_self_check.bat or scripts/run_validation_suite.bat)
git add <changed files>
git commit -m "Describe the completed change"
git push
```

Update `docs/internal_handoff/CURRENT_HANDOFF_KR.md` (and `docs/internal_handoff/CURRENT_HANDOFF.md`) whenever the current focus, next tasks, or project state changes.

## Research Accuracy

Do not claim the reference papers are fully implemented until the backend has:

- real Abaqus contact/friction pairs
- periodic boundary conditions
- cyclic bending boundary conditions
- actual Abaqus job submission
- ODB extraction into `result_data.csv`
- calibrated friction/residual contact pressure behavior
- coupled torsion/tension/compression load cases
- local slip/contact pressure/stress summaries

The current GUI is literature-informed, but the Abaqus backend is still the
source of truth for final research validation.

## Design Direction

The GUI should feel like a clean modern engineering application:

- Apple/Codex-like light interface
- HELIX branding
- English labels by default
- Korean toggle where already supported
- resizable side panels
- scroll-safe layouts for laptop and desktop screens
- no clipped bottom controls
- restrained, precise visual hierarchy

Avoid adding unrelated decorative UI or large refactors unless the user asks.

## Files To Avoid Committing

Do not commit local/generated artifacts unless the user explicitly asks:

- virtual environments
- generated job folders
- Abaqus output files such as `.odb`, `.sim`, `.cae`, `.sta`, `.msg`
- local machine settings
- Python caches
- macOS/Windows metadata

