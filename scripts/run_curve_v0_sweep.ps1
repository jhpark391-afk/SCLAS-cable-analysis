param(
    [string]$JobDir = "",
    [double[]]$CurveFactors = @(-0.1, -0.05, 0.0, 0.05, 0.1),
    [int]$SmallAxialDivisions = 4,
    [int]$SmallCoreCircumferentialDivisions = 8,
    [int]$SmallArmourCircumferentialDivisions = 4,
    [double]$SmallEffectiveLengthMm = 50.0,
    [double]$ContactClosureOverclosureMm = 0.0
)

$ErrorActionPreference = "Stop"

function Resolve-ProjectRoot {
    if ($PSScriptRoot) {
        return Split-Path $PSScriptRoot -Parent
    }
    return Split-Path (Get-Location).Path -Parent
}

function Find-LatestGuiJobDir {
    param([string]$ProjectRoot)
    $jobsRoot = Join-Path $ProjectRoot "jobs\SCLAS_jobs"
    $candidate = Get-ChildItem $jobsRoot -Directory |
        Where-Object { $_.Name -like "job_*" -and (Test-Path (Join-Path $_.FullName "input_data.json")) } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $candidate) {
        throw "No GUI job_* folder with input_data.json was found under $jobsRoot."
    }
    return $candidate.FullName
}

function Read-LastCsvDataRow {
    param([string]$CsvPath)
    if (-not (Test-Path $CsvPath)) {
        throw "Missing result CSV: $CsvPath"
    }
    $rows = @(Import-Csv $CsvPath)
    if ($rows.Count -lt 1) {
        throw "No data rows in result CSV: $CsvPath"
    }
    return $rows[-1]
}

function Read-JsonFile {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        throw "Missing JSON file: $Path"
    }
    try {
        return Get-Content $Path -Raw | ConvertFrom-Json
    } catch {
        throw "Could not parse JSON file $Path`: $($_.Exception.Message)"
    }
}

function Format-InvariantDouble {
    param([double]$Value)
    return [string]::Format([System.Globalization.CultureInfo]::InvariantCulture, "{0:R}", $Value)
}

function Assert-ChildOdbResult {
    param(
        [Parameter(Mandatory=$true)]$Child,
        [Parameter(Mandatory=$true)][double]$Factor
    )
    $summaryPath = Join-Path $Child.FullName "result_summary.json"
    $summary = Read-JsonFile $summaryPath
    $odb = $summary.odb_extraction
    $quality = $summary.abaqus_result_quality

    if ($summary.source -ne "SCLAS_ABAQUS_ODB_EXTRACTOR") {
        throw "Curve factor $Factor did not produce an ODB-extracted result. Source was '$($summary.source)' in $summaryPath"
    }
    if ($summary.status -ne "completed") {
        throw "Curve factor $Factor summary status was '$($summary.status)' in $summaryPath"
    }
    if (-not $odb -or $odb.status -ne "extracted") {
        $reason = if ($odb) { $odb.reason } else { "missing odb_extraction block" }
        throw "Curve factor $Factor ODB extraction was not successful: $reason"
    }
    if ([int]$odb.rows_written -lt 2) {
        throw "Curve factor $Factor wrote too few ODB rows: $($odb.rows_written)"
    }
    if (-not $quality -or $quality.curve_class -eq "odb_extraction_failed" -or $quality.curve_class -eq "too_few_odb_rows") {
        throw "Curve factor $Factor has unacceptable result quality: $($quality.curve_class)"
    }

    return [pscustomobject]@{
        source = $summary.source
        status = $summary.status
        odb_status = $odb.status
        odb_rows_written = [int]$odb.rows_written
        curve_class = $quality.curve_class
        is_research_curve = [bool]$quality.is_research_curve
    }
}

function Write-Utf8NoBom {
    param([string]$Path, [string[]]$Lines)
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($Path, $Lines, $utf8NoBom)
}

$ProjectRoot = Resolve-ProjectRoot
$RunSmokeScript = Join-Path $ProjectRoot "run_lab_abaqus_smoke.ps1"
if (-not (Test-Path $RunSmokeScript)) {
    throw "run_lab_abaqus_smoke.ps1 was not found: $RunSmokeScript"
}
if ($ContactClosureOverclosureMm -lt 0.0) {
    throw "-ContactClosureOverclosureMm must be zero or positive."
}

if (-not $JobDir) {
    $JobDir = Find-LatestGuiJobDir $ProjectRoot
}
$SourceJobDir = (Resolve-Path $JobDir).Path
$jobsRoot = Join-Path $ProjectRoot "jobs\SCLAS_jobs"
if (-not (Test-Path $jobsRoot)) {
    New-Item -ItemType Directory -Path $jobsRoot -Force | Out-Null
}

$sweepName = "curve_v0_sweep_" + (Get-Date -Format "yyyyMMdd_HHmmss")
$sweepDir = Join-Path $jobsRoot $sweepName
New-Item -ItemType Directory -Path $sweepDir -Force | Out-Null

Write-Host "=== SCLAS Curve V0 Endpoint Sweep ===" -ForegroundColor Cyan
Write-Host "Project: $ProjectRoot"
Write-Host "Source:  $SourceJobDir"
Write-Host "Sweep:   $sweepDir"
Write-Host "Factors: $($CurveFactors -join ', ')"
Write-Host "Contact closure overclosure mm: $(Format-InvariantDouble $ContactClosureOverclosureMm)"

$curveRows = New-Object System.Collections.Generic.List[string]
$curveRows.Add("curvature_1_per_m,moment_kn_m")
$childJobs = @()

foreach ($factor in $CurveFactors) {
    Write-Host ""
    Write-Host "=== Curve point factor $factor ===" -ForegroundColor Cyan
    $pointStart = Get-Date
    & powershell -ExecutionPolicy Bypass -File $RunSmokeScript `
        -JobDir $SourceJobDir `
        -CurveV0 `
        -CurveV0CurvatureScale $factor `
        -SmallAxialDivisions $SmallAxialDivisions `
        -SmallCoreCircumferentialDivisions $SmallCoreCircumferentialDivisions `
        -SmallArmourCircumferentialDivisions $SmallArmourCircumferentialDivisions `
        -SmallEffectiveLengthMm $SmallEffectiveLengthMm `
        -ContactClosureOverclosureMm $ContactClosureOverclosureMm

    $child = Get-ChildItem $jobsRoot -Directory -Filter "curve_v0_*" |
        Where-Object { $_.Name -notlike "curve_v0_sweep_*" } |
        Where-Object { $_.LastWriteTime -ge $pointStart.AddSeconds(-5) } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $child) {
        throw "Could not find the curve_v0 child job after factor $factor"
    }
    $validation = Assert-ChildOdbResult -Child $child -Factor $factor
    $csvPath = Join-Path $child.FullName "result_data.csv"
    $row = Read-LastCsvDataRow $csvPath
    $curvature = [double]::Parse($row.curvature_1_per_m, [System.Globalization.CultureInfo]::InvariantCulture)
    $moment = [double]::Parse($row.moment_kn_m, [System.Globalization.CultureInfo]::InvariantCulture)
    $curveRows.Add(("{0},{1}" -f (Format-InvariantDouble $curvature), (Format-InvariantDouble $moment)))
    $childJobs += [pscustomobject]@{
        factor = [double]$factor
        job = $child.Name
        path = $child.FullName
        curvature_1_per_m = $curvature
        moment_kn_m = $moment
        source = $validation.source
        odb_status = $validation.odb_status
        odb_rows_written = $validation.odb_rows_written
        curve_class = $validation.curve_class
    }
}

$resultCsv = Join-Path $sweepDir "result_data.csv"
$curveLines = $curveRows.ToArray()
Write-Utf8NoBom -Path $resultCsv -Lines $curveLines

$summary = [pscustomobject]@{
    source = "SCLAS_CURVE_V0_ENDPOINT_SWEEP"
    status = "completed"
    num_points = $childJobs.Count
    result_contract = [pscustomobject]@{
        csv_file = "result_data.csv"
        required_columns = @("curvature_1_per_m", "moment_kn_m")
        summary_file = "result_summary.json"
        primary_result = "bending moment-curvature endpoint sweep"
    }
    mesh_status = [pscustomobject]@{
        status = "endpoint_sweep_parent"
        child_job_count = $childJobs.Count
    }
    backend_readiness = [pscustomobject]@{
        bending_stick_slip = [pscustomobject]@{
            requested = $true
            status = "abaqus_endpoint_sweep_curve_v0"
            next_step = "Validate endpoint sweep shape against a continuous bending load path before research use."
        }
        source = "SCLAS_CURVE_V0_ENDPOINT_SWEEP"
    }
    abaqus_result_quality = [pscustomobject]@{
        curve_class = $(if ($childJobs.Count -ge 5) { "endpoint_sweep_curve_v0" } else { "endpoint_sweep_partial" })
        is_research_curve = $false
        backend_readiness_status = "abaqus_endpoint_sweep_curve_v0"
        next_step = "Treat this as a candidate Abaqus endpoint curve; validate shape, contact warnings, and a continuous bending path before research use."
    }
    curve_factors = $CurveFactors
    rows_written = $childJobs.Count
    endpoint_sweep_validation = [pscustomobject]@{
        required_child_source = "SCLAS_ABAQUS_ODB_EXTRACTOR"
        required_child_odb_status = "extracted"
        all_child_jobs_validated = $true
        aggregation_rule = "last ODB-extracted CSV row from each child job"
    }
    child_jobs = $childJobs
    created_at = (Get-Date).ToString("s")
}
$summaryJson = Join-Path $sweepDir "result_summary.json"
$jsonText = $summary | ConvertTo-Json -Depth 100
Write-Utf8NoBom -Path $summaryJson -Lines @($jsonText)

Write-Host ""
Write-Host "=== Curve V0 sweep complete ===" -ForegroundColor Cyan
Write-Host "Result CSV: $resultCsv"
Write-Host "Summary:    $summaryJson"
Get-Content $resultCsv
