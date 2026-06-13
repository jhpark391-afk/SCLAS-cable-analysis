param(
    [string]$JobDir = "",
    [switch]$GenerateOnly,
    [switch]$SkipGeneration
)

$ErrorActionPreference = "Stop"

function Write-Section {
    param([string]$Title)
    Write-Host ""
    Write-Host "=== $Title ===" -ForegroundColor Cyan
}

function Resolve-ProjectRoot {
    if ($PSScriptRoot) {
        return $PSScriptRoot
    }
    return (Get-Location).Path
}

function Find-LatestJobDir {
    param([string]$ProjectRoot)
    $jobsRoot = Join-Path $ProjectRoot "jobs\SCLAS_jobs"
    if (-not (Test-Path $jobsRoot)) {
        throw "jobs\SCLAS_jobs was not found. Export a GUI job package first."
    }
    $candidate = Get-ChildItem $jobsRoot -Directory |
        Where-Object { $_.Name -like "job_*" -and (Test-Path (Join-Path $_.FullName "input_data.json")) } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $candidate) {
        throw "No GUI job_* folder with input_data.json was found under $jobsRoot."
    }
    return $candidate.FullName
}

function Show-ManifestSummary {
    param([string]$ResolvedJobDir)
    $manifestPath = Join-Path $ResolvedJobDir "abaqus_mesh_manifest.json"
    if (-not (Test-Path $manifestPath)) {
        Write-Host "No abaqus_mesh_manifest.json yet."
        return
    }
    try {
        $manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
    } catch {
        Write-Host "Could not parse abaqus_mesh_manifest.json: $($_.Exception.Message)" -ForegroundColor Yellow
        return
    }
    Write-Host "mesh status: $($manifest.status)"
    Write-Host "contact pair status: $($manifest.contact_pair_scaffold_status)"
    Write-Host "boundary condition status: $($manifest.boundary_condition_scaffold_status)"
    if ($manifest.boundary_condition_scaffold) {
        $bc = $manifest.boundary_condition_scaffold
        Write-Host "BC scaffold status: $($bc.status)"
        if ($bc.keyword_coupling_fallback) {
            Write-Host "keyword fallback: $($bc.keyword_coupling_fallback.status)"
        }
    }
}

function Find-NormalPython {
    param([string]$ProjectRoot)
    $venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        return $venvPython
    }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return "py -3"
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return "python"
    }
    return $null
}

$ProjectRoot = Resolve-ProjectRoot
if (-not $JobDir) {
    $JobDir = Find-LatestJobDir $ProjectRoot
}
$JobDir = (Resolve-Path $JobDir).Path

$RunnerSource = Join-Path $ProjectRoot "code\abaqus_runner.py"
$RunnerDest = Join-Path $JobDir "abaqus_runner.py"
if (-not (Test-Path $RunnerSource)) {
    throw "Runner source was not found: $RunnerSource"
}
if (-not (Test-Path (Join-Path $JobDir "input_data.json"))) {
    throw "input_data.json was not found in job folder: $JobDir"
}

Write-Section "SCLAS Lab Abaqus Smoke"
Write-Host "Project: $ProjectRoot"
Write-Host "Job:     $JobDir"
Write-Host "Mode:    $(if ($GenerateOnly) { 'generate only' } elseif ($SkipGeneration) { 'solver only' } else { 'generate + solver' })"

Copy-Item $RunnerSource $RunnerDest -Force
Write-Host "Copied latest code\abaqus_runner.py into the job folder."

if (-not $SkipGeneration) {
    Write-Section "Abaqus/CAE noGUI generation"
    Push-Location $JobDir
    try {
        cmd /c "abaqus cae noGUI=abaqus_runner.py -- input_data.json > abaqus_stdout.txt 2>&1"
    } finally {
        Pop-Location
    }
    Get-Content (Join-Path $JobDir "abaqus_stdout.txt") -Raw
    Show-ManifestSummary $JobDir
}

$inp = Get-ChildItem $JobDir -Filter "*_mes.inp" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if (-not $inp) {
    throw "No *_mes.inp file was found. Check abaqus_stdout.txt and abaqus_mesh_manifest.json."
}
$jobName = [IO.Path]::GetFileNameWithoutExtension($inp.Name)
Write-Host "Input deck: $($inp.Name)"
Write-Host "Solver job: $jobName"

if ($GenerateOnly) {
    Write-Section "Stopped before solver submit"
    Write-Host "Generation finished. Re-run without -GenerateOnly to submit the solver."
    exit 0
}

Write-Section "Abaqus solver submit"
Push-Location $JobDir
try {
    cmd /c "abaqus job=$jobName input=$($inp.Name) interactive > solver_stdout.txt 2>&1"
} finally {
    Pop-Location
}

Write-Section "solver_stdout.txt"
Get-Content (Join-Path $JobDir "solver_stdout.txt") -Raw

Write-Section "Generated solver files"
Get-ChildItem $JobDir -Filter "$jobName.*" |
    Select-Object Name,Length,LastWriteTime |
    Format-Table -AutoSize

Write-Section "First blocking log context"
$logFiles = @(
    (Join-Path $JobDir "solver_stdout.txt"),
    (Join-Path $JobDir "$jobName.dat"),
    (Join-Path $JobDir "$jobName.msg"),
    (Join-Path $JobDir "$jobName.sta"),
    (Join-Path $JobDir "$jobName.com"),
    (Join-Path $JobDir "$jobName.prt")
) | Where-Object { Test-Path $_ }

$extractPath = Join-Path $JobDir "solver_error_extract.txt"
if ($logFiles.Count -eq 0) {
    Write-Host "No solver logs found."
} else {
    $blockingPattern = "\*\*\*ERROR|FATAL|SEVERE|THE PROGRAM HAS DISCOVERED|Abaqus Error|Abaqus/Analysis exited|UNKNOWN|INVALID|MISPLACED|ZERO PIVOT|OVERCONSTRAINT|TOO MANY|EXCESSIVE|DISTORTION"
    $notablePattern = "WARNING|COUPLING|KINEMATIC|REF NODE"
    $matches = @(Select-String -Path $logFiles `
        -Pattern $blockingPattern `
        -Context 3,3 |
        Select-Object -First 120)
    if ($matches.Count -eq 0) {
        $matches = @(Select-String -Path $logFiles `
            -Pattern $notablePattern `
            -Context 3,3 |
            Select-Object -First 80)
    }
    $matches | Out-File $extractPath -Encoding utf8
    if ($matches) {
        $matches | Select-Object -First 80
        Write-Host ""
        Write-Host "Saved full extract to $extractPath"
    } else {
        Write-Host "No matching error/warning context found in solver logs."
    }
}

$diagPython = Find-NormalPython $ProjectRoot
$diagScript = Join-Path $ProjectRoot "code\sclas_offline_diagnostics.py"
if ($diagPython -and (Test-Path $diagScript)) {
    Write-Section "Offline diagnostics report"
    if ($diagPython -eq "py -3") {
        py -3 $diagScript $JobDir --save-report --save-markdown
    } elseif ($diagPython -eq "python") {
        python $diagScript $JobDir --save-report --save-markdown
    } else {
        & $diagPython $diagScript $JobDir --save-report --save-markdown
    }
} else {
    Write-Section "Offline diagnostics skipped"
    Write-Host "Normal Python was not found. The PowerShell error extract was still saved."
}
