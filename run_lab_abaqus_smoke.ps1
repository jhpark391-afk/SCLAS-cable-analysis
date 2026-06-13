param(
    [string]$JobDir = "",
    [switch]$GenerateOnly,
    [switch]$SkipGeneration,
    [switch]$SmallSmoke,
    [int]$SmallAxialDivisions = 4,
    [int]$SmallCoreCircumferentialDivisions = 8,
    [int]$SmallArmourCircumferentialDivisions = 4,
    [double]$SmallEffectiveLengthMm = 50.0,
    [int]$SmallAbaqusOutputIntervals = 4
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

function Ensure-JsonObjectProperty {
    param(
        [Parameter(Mandatory=$true)]$Object,
        [Parameter(Mandatory=$true)][string]$Name
    )
    if (-not $Object.PSObject.Properties[$Name]) {
        $Object | Add-Member -MemberType NoteProperty -Name $Name -Value ([pscustomobject]@{})
    }
    return $Object.$Name
}

function Set-JsonObjectProperty {
    param(
        [Parameter(Mandatory=$true)]$Object,
        [Parameter(Mandatory=$true)][string]$Name,
        $Value
    )
    if ($Object.PSObject.Properties[$Name]) {
        $Object.$Name = $Value
    } else {
        $Object | Add-Member -MemberType NoteProperty -Name $Name -Value $Value
    }
}

function New-SmallSmokeJob {
    param(
        [Parameter(Mandatory=$true)][string]$ProjectRoot,
        [Parameter(Mandatory=$true)][string]$SourceJobDir,
        [Parameter(Mandatory=$true)][int]$AxialDivisions,
        [Parameter(Mandatory=$true)][int]$CoreCircumferentialDivisions,
        [Parameter(Mandatory=$true)][int]$ArmourCircumferentialDivisions,
        [Parameter(Mandatory=$true)][double]$EffectiveLengthMm,
        [Parameter(Mandatory=$true)][int]$AbaqusOutputIntervals
    )

    $jobsRoot = Join-Path $ProjectRoot "jobs\SCLAS_jobs"
    if (-not (Test-Path $jobsRoot)) {
        New-Item -ItemType Directory -Path $jobsRoot -Force | Out-Null
    }
    $smallName = "small_smoke_" + (Get-Date -Format "yyyyMMdd_HHmmss")
    $smallDir = Join-Path $jobsRoot $smallName
    New-Item -ItemType Directory -Path $smallDir -Force | Out-Null

    foreach ($fileName in @("input_data.json", "units_manifest.json", "BACKEND_CONTRACT.md")) {
        $sourcePath = Join-Path $SourceJobDir $fileName
        if (Test-Path $sourcePath) {
            Copy-Item $sourcePath (Join-Path $smallDir $fileName) -Force
        }
    }

    $inputPath = Join-Path $smallDir "input_data.json"
    if (-not (Test-Path $inputPath)) {
        throw "input_data.json was not found in source job folder: $SourceJobDir"
    }

    $payload = Get-Content $inputPath -Raw | ConvertFrom-Json
    $mesh = Ensure-JsonObjectProperty $payload "mesh"
    $analysis = Ensure-JsonObjectProperty $payload "analysis_conditions"
    $metadata = Ensure-JsonObjectProperty $payload "metadata"

    Set-JsonObjectProperty $mesh "axial_divisions" ([int]$AxialDivisions)
    Set-JsonObjectProperty $mesh "core_circumferential_divisions" ([int]$CoreCircumferentialDivisions)
    Set-JsonObjectProperty $mesh "armour_circumferential_divisions" ([int]$ArmourCircumferentialDivisions)
    Set-JsonObjectProperty $mesh "lab_smoke_reduced_mesh" $true
    Set-JsonObjectProperty $analysis "effective_length_mm" ([double]$EffectiveLengthMm)
    Set-JsonObjectProperty $analysis "abaqus_output_intervals" ([int]$AbaqusOutputIntervals)
    Set-JsonObjectProperty $analysis "abaqus_multistep_smoke" $true
    if ($analysis.PSObject.Properties["solver_steps"]) {
        $analysis.solver_steps = 25
    }
    Set-JsonObjectProperty $metadata "job_id" $smallName
    Set-JsonObjectProperty $metadata "lab_smoke_source_job" (Split-Path -Leaf $SourceJobDir)

    $jsonText = $payload | ConvertTo-Json -Depth 100
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($inputPath, $jsonText + [Environment]::NewLine, $utf8NoBom)

    Write-Host "Created reduced smoke job: $smallDir"
    Write-Host "  axial_divisions=$AxialDivisions, core_circ=$CoreCircumferentialDivisions, armour_circ=$ArmourCircumferentialDivisions, effective_length_mm=$EffectiveLengthMm, abaqus_output_intervals=$AbaqusOutputIntervals"
    return $smallDir
}

$ProjectRoot = Resolve-ProjectRoot
if (-not $JobDir) {
    $JobDir = Find-LatestJobDir $ProjectRoot
}
$SourceJobDir = (Resolve-Path $JobDir).Path
if ($SmallSmoke -and $SkipGeneration) {
    throw "-SmallSmoke cannot be combined with -SkipGeneration because the reduced job has no generated .inp yet."
}
if ($SmallSmoke) {
    $JobDir = New-SmallSmokeJob `
        -ProjectRoot $ProjectRoot `
        -SourceJobDir $SourceJobDir `
        -AxialDivisions $SmallAxialDivisions `
        -CoreCircumferentialDivisions $SmallCoreCircumferentialDivisions `
        -ArmourCircumferentialDivisions $SmallArmourCircumferentialDivisions `
        -EffectiveLengthMm $SmallEffectiveLengthMm `
        -AbaqusOutputIntervals $SmallAbaqusOutputIntervals
} else {
    $JobDir = $SourceJobDir
}
$JobDir = (Resolve-Path $JobDir).Path

$RunnerSource = Join-Path $ProjectRoot "code\abaqus_runner.py"
$RunnerDest = Join-Path $JobDir "abaqus_runner.py"
$ExtractorSource = Join-Path $ProjectRoot "code\sclas_odb_extractor.py"
$ExtractorDest = Join-Path $JobDir "sclas_odb_extractor.py"
if (-not (Test-Path $RunnerSource)) {
    throw "Runner source was not found: $RunnerSource"
}
if (-not (Test-Path (Join-Path $JobDir "input_data.json"))) {
    throw "input_data.json was not found in job folder: $JobDir"
}

Write-Section "SCLAS Lab Abaqus Smoke"
Write-Host "Project: $ProjectRoot"
if ($SmallSmoke) {
    Write-Host "Source:  $SourceJobDir"
}
Write-Host "Job:     $JobDir"
Write-Host "Mode:    $(if ($SmallSmoke -and $GenerateOnly) { 'small smoke generate only' } elseif ($SmallSmoke) { 'small smoke generate + solver' } elseif ($GenerateOnly) { 'generate only' } elseif ($SkipGeneration) { 'solver only' } else { 'generate + solver' })"

Copy-Item $RunnerSource $RunnerDest -Force
Write-Host "Copied latest code\abaqus_runner.py into the job folder."
if (Test-Path $ExtractorSource) {
    Copy-Item $ExtractorSource $ExtractorDest -Force
    Write-Host "Copied latest code\sclas_odb_extractor.py into the job folder."
}

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

$inp = Get-ChildItem $JobDir -Filter "*.inp" |
    Where-Object { $_.BaseName -like "*_mesh" -or $_.BaseName -like "*_mes" } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if (-not $inp) {
    $inpCandidates = Get-ChildItem $JobDir -Filter "*.inp" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -ExpandProperty Name
    if ($inpCandidates) {
        throw "No generated *_mesh.inp or *_mes.inp file was found. Available .inp files: $($inpCandidates -join ', ')"
    }
    throw "No Abaqus .inp file was found. Check abaqus_stdout.txt and abaqus_mesh_manifest.json."
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
$solverStdoutPath = Join-Path $JobDir "solver_stdout.txt"
$solverStdoutText = Get-Content $solverStdoutPath -Raw
$solverStdoutText
$solverCompleted = $solverStdoutText -match "Abaqus JOB .* COMPLETED|COMPLETED SUCCESSFULLY"

Write-Section "Generated solver files"
Get-ChildItem $JobDir -Filter "$jobName.*" |
    Select-Object Name,Length,LastWriteTime |
    Format-Table -AutoSize

$odbPath = Join-Path $JobDir "$jobName.odb"
if ($solverCompleted -and (Test-Path $ExtractorDest) -and (Test-Path $odbPath)) {
    Write-Section "ODB extraction"
    Push-Location $JobDir
    try {
        cmd /c "abaqus python sclas_odb_extractor.py $($jobName).odb --job-dir . --input-data input_data.json > odb_extract_stdout.txt 2>&1"
    } finally {
        Pop-Location
    }
    Get-Content (Join-Path $JobDir "odb_extract_stdout.txt") -Raw
    if (Test-Path (Join-Path $JobDir "odb_extraction_summary.json")) {
        Get-Content (Join-Path $JobDir "odb_extraction_summary.json") -Raw
    }
} elseif ($solverCompleted) {
    Write-Section "ODB extraction skipped"
    Write-Host "Solver completed, but extractor or ODB was not found."
}

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
    $blockingPattern = "\*\*\*ERROR|FATAL|THE PROGRAM HAS DISCOVERED|Abaqus Error|Abaqus/Analysis exited with errors|exited with errors|UNKNOWN|INVALID|MISPLACED"
    $notablePattern = "WARNING|ZERO PIVOT|OVERCONSTRAINT|TOO MANY|EXCESSIVE|DISTORTION|COUPLING|KINEMATIC|REF NODE"
    $matches = @(Select-String -Path $logFiles `
        -Pattern $blockingPattern `
        -Context 3,3 |
        Select-Object -First 120)
    if ($matches.Count -eq 0 -and -not $solverCompleted) {
        $matches = @(Select-String -Path $logFiles `
            -Pattern $notablePattern `
            -Context 3,3 |
            Select-Object -First 80)
    }
    if ($matches.Count -eq 0 -and $solverCompleted) {
        "Solver completed; no blocking error context found." | Out-File $extractPath -Encoding utf8
    } else {
        $matches | Out-File $extractPath -Encoding utf8
    }
    if ($matches) {
        $matches | Select-Object -First 80
        Write-Host ""
        Write-Host "Saved full extract to $extractPath"
    } elseif ($solverCompleted) {
        Write-Host "Solver completed; no blocking error context found."
        Write-Host "Saved completion note to $extractPath"
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
