param(
    [string]$JobDir = "",
    [double]$CurveScale = 0.1,
    [double[]]$PathFactors = @(1.0, 0.0, -1.0, 0.0),
    [int]$SmallAxialDivisions = 4,
    [int]$SmallCoreCircumferentialDivisions = 8,
    [int]$SmallArmourCircumferentialDivisions = 4,
    [double]$SmallEffectiveLengthMm = 50.0,
    [int]$SmallAbaqusOutputIntervals = 4,
    [double]$ContactClosureOverclosureMm = 0.0
)

$ErrorActionPreference = "Stop"

function Resolve-ProjectRoot {
    if ($PSScriptRoot) {
        return $PSScriptRoot
    }
    return (Get-Location).Path
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

function Write-Utf8NoBom {
    param([string]$Path, [string]$Text)
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Text, $utf8NoBom)
}

function Format-InvariantDouble {
    param([double]$Value)
    return [string]::Format([System.Globalization.CultureInfo]::InvariantCulture, "{0:R}", $Value)
}

if ($CurveScale -le 0.0) {
    throw "-CurveScale must be positive."
}
if (-not $PathFactors -or $PathFactors.Count -lt 2) {
    throw "-PathFactors must contain at least two numeric values."
}
if ($ContactClosureOverclosureMm -lt 0.0) {
    throw "-ContactClosureOverclosureMm must be zero or positive."
}

$ProjectRoot = Resolve-ProjectRoot
$RunSmokeScript = Join-Path $ProjectRoot "run_lab_abaqus_smoke.ps1"
if (-not (Test-Path $RunSmokeScript)) {
    throw "run_lab_abaqus_smoke.ps1 was not found: $RunSmokeScript"
}

if (-not $JobDir) {
    $JobDir = Find-LatestGuiJobDir $ProjectRoot
}
$SourceJobDir = (Resolve-Path $JobDir).Path
$jobsRoot = Join-Path $ProjectRoot "jobs\SCLAS_jobs"
if (-not (Test-Path $jobsRoot)) {
    New-Item -ItemType Directory -Path $jobsRoot -Force | Out-Null
}

$sourceName = "continuous_curve_v0_source_" + (Get-Date -Format "yyyyMMdd_HHmmss")
$continuousSourceDir = Join-Path $jobsRoot $sourceName
New-Item -ItemType Directory -Path $continuousSourceDir -Force | Out-Null

foreach ($fileName in @("input_data.json", "units_manifest.json", "BACKEND_CONTRACT.md")) {
    $sourcePath = Join-Path $SourceJobDir $fileName
    if (Test-Path $sourcePath) {
        Copy-Item $sourcePath (Join-Path $continuousSourceDir $fileName) -Force
    }
}

$inputPath = Join-Path $continuousSourceDir "input_data.json"
if (-not (Test-Path $inputPath)) {
    throw "input_data.json was not found in source job folder: $SourceJobDir"
}

$payload = Read-JsonFile $inputPath
$analysis = Ensure-JsonObjectProperty $payload "analysis_conditions"
$metadata = Ensure-JsonObjectProperty $payload "metadata"

$baseCurvature = 0.08
if ($analysis.PSObject.Properties["max_curvature_1_per_m"]) {
    $baseCurvature = [double]$analysis.max_curvature_1_per_m
}
$continuousCurvature = $baseCurvature * $CurveScale

Set-JsonObjectProperty $analysis "max_curvature_1_per_m" ([double]$continuousCurvature)
Set-JsonObjectProperty $analysis "abaqus_curve_v0_path_factors" ([double[]]$PathFactors)
Set-JsonObjectProperty $metadata "job_id" $sourceName
Set-JsonObjectProperty $metadata "analysis_mode" "continuous_curve_v0_source"
Set-JsonObjectProperty $metadata "continuous_curve_v0_base_curvature_1_per_m" ([double]$baseCurvature)
Set-JsonObjectProperty $metadata "continuous_curve_v0_curve_scale" ([double]$CurveScale)

Write-Utf8NoBom $inputPath (($payload | ConvertTo-Json -Depth 100) + [Environment]::NewLine)

Write-Host "=== SCLAS Continuous Curve V0 ===" -ForegroundColor Cyan
Write-Host "Project: $ProjectRoot"
Write-Host "Source:  $SourceJobDir"
Write-Host "Prepared continuous source: $continuousSourceDir"
Write-Host "Curve scale: $CurveScale"
Write-Host "Base curvature: $(Format-InvariantDouble $baseCurvature)"
Write-Host "Continuous max curvature: $(Format-InvariantDouble $continuousCurvature)"
Write-Host "Path factors: $($PathFactors -join ', ')"
Write-Host "Contact closure overclosure mm: $(Format-InvariantDouble $ContactClosureOverclosureMm)"

$runStart = Get-Date
& powershell -ExecutionPolicy Bypass -File $RunSmokeScript `
    -JobDir $continuousSourceDir `
    -CurveV0 `
    -MultiStepSmoke `
    -CurveV0CurvatureScale 1.0 `
    -SmallAxialDivisions $SmallAxialDivisions `
    -SmallCoreCircumferentialDivisions $SmallCoreCircumferentialDivisions `
    -SmallArmourCircumferentialDivisions $SmallArmourCircumferentialDivisions `
    -SmallEffectiveLengthMm $SmallEffectiveLengthMm `
    -SmallAbaqusOutputIntervals $SmallAbaqusOutputIntervals `
    -ContactClosureOverclosureMm $ContactClosureOverclosureMm
if ($LASTEXITCODE -ne 0) {
    throw "run_lab_abaqus_smoke.ps1 failed with exit code $LASTEXITCODE"
}

$job = Get-ChildItem $jobsRoot -Directory |
    Where-Object {
        $_.Name -like "curve_v0_*" -and
        $_.Name -notlike "curve_v0_sweep_*" -and
        $_.LastWriteTime -ge $runStart.AddSeconds(-5)
    } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if (-not $job) {
    throw "Could not locate the continuous curve_v0 child job created after $runStart."
}

$summaryPath = Join-Path $job.FullName "result_summary.json"
$summary = Read-JsonFile $summaryPath
$odb = $summary.odb_extraction
$quality = $summary.abaqus_result_quality
$csvPath = Join-Path $job.FullName "result_data.csv"
$rows = @(Import-Csv $csvPath)

if ($summary.source -ne "SCLAS_ABAQUS_ODB_EXTRACTOR") {
    throw "Continuous CurveV0 did not produce an ODB-extracted result. Source was '$($summary.source)' in $summaryPath"
}
if (-not $odb -or $odb.status -ne "extracted") {
    $reason = if ($odb) { $odb.reason } else { "missing odb_extraction block" }
    throw "Continuous CurveV0 ODB extraction was not successful: $reason"
}
if ([int]$odb.rows_written -lt 5) {
    throw "Continuous CurveV0 wrote too few ODB rows: $($odb.rows_written)"
}
if ($rows.Count -lt 5) {
    throw "Continuous CurveV0 result_data.csv has too few data rows: $($rows.Count)"
}
if (-not $quality -or $quality.curve_class -ne "multi_point_curve_v0") {
    throw "Continuous CurveV0 was not classified as multi_point_curve_v0. Curve class: $($quality.curve_class)"
}

Write-Host ""
Write-Host "=== Continuous Curve V0 complete ===" -ForegroundColor Cyan
Write-Host "Job:      $($job.FullName)"
Write-Host "CSV:      $csvPath"
Write-Host "Summary:  $summaryPath"
Write-Host "Rows:     $($rows.Count)"
Write-Host "Class:    $($quality.curve_class)"
Get-Content $csvPath
