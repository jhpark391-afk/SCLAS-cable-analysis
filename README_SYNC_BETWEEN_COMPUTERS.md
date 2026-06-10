# Syncing SCLAS Between Computers

Codex does not automatically synchronize local files between your Mac and your
Windows desktop. Use GitHub, OneDrive, or a manual zip transfer.

## Recommended GitHub flow

On the Mac:

```bash
cd 01_SCLAS_케이블해석
git init
git add .
git commit -m "Prepare SCLAS for Windows development"
git branch -M main
git remote add origin https://github.com/YOUR_ID/YOUR_REPO.git
git push -u origin main
```

On Windows:

```bat
git clone https://github.com/YOUR_ID/YOUR_REPO.git
cd YOUR_REPO
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
git add .
git commit -m "Describe change"
git push
```
