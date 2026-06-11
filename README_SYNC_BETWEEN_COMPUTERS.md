# Syncing SCLAS Between Computers

Codex does not automatically synchronize local files between your Mac and your
Windows desktop. Use GitHub, OneDrive, or a manual zip transfer.

For this repository, the recommended source of truth is:

```text
https://github.com/jhpark391-afk/SCLAS-cable-analysis
```

Each Codex session should read:

```text
AGENTS.md
CURRENT_HANDOFF.md
```

## Recommended GitHub flow

On the Mac:

```bash
cd 01_SCLAS_케이블해석
git pull
git status --short --branch
# work, verify, then:
git add <changed files>
git commit -m "Describe change"
git push
```

On Windows:

```bat
git clone https://github.com/jhpark391-afk/SCLAS-cable-analysis.git
cd SCLAS-cable-analysis
setup_windows.bat
run_sclas.bat
```

## What should not be synced

The `.gitignore` excludes:

- `.venv`, `venv`, `90_env`
- Python caches
- macOS and Windows desktop metadata
- generated `jobs/SCLAS_jobs/job_*` folders
- large Abaqus output files such as `.odb`, `.sim`, `.cae`, `.sta`, `.msg`

If you need to share one specific job package, zip that one job folder manually
or temporarily force-add it to Git with care.

## Codex on both computers

Once the same Git repository exists on both machines, Codex can work on each
local checkout. The actual synchronization still happens through Git operations:

```bash
git pull
git status --short --branch
git add .
git commit -m "Describe change"
git push
```

Update `CURRENT_HANDOFF.md` before committing when the next task, current
limitations, or important file list changes.
