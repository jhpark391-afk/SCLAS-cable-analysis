param(
    [string]$JobDir = "",
    [switch]$GenerateOnly,
    [switch]$SkipGeneration,
    [switch]$SmallSmoke,
    [int]$SmallAxialDivisions = 4,
    [int]$SmallCoreCircumferentialDivisions = 8,
    [int]$SmallArmourCircumferentialDivisions = 4,
    [double]$SmallEffectiveLengthMm = 50.0,
    [int]$SmallAbaqusOutputIntervals = 4,
    [switch]$MultiStepSmoke,
    [switch]$CurveV0,
    [double]$CurveV0CurvatureScale = 0.1,
    [double]$ContactClosureOverclosureMm = 0.0
)

$ErrorActionPreference = "Stop"

function Write-Section {
    param([string]$Title)
    Write-Host ""
    Write-Host "=== $Title ===" -ForegroundColor Cyan
}

function Resolve-ProjectRoot {
    if ($PSScriptRoot) {
        return Split-Path $PSScriptRoot -Parent
    }
    return Split-Path (Get-Location).Path -Parent
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
    if ($manifest.contact_initial_clearance_summary) {
        $clearance = $manifest.contact_initial_clearance_summary
        Write-Host "contact clearance: status=$($clearance.status), checked=$($clearance.checked_pair_count), gapped=$($clearance.gapped_pair_count), touching=$($clearance.touching_pair_count), overclosed=$($clearance.overclosed_pair_count), preload=$($clearance.residual_pressure_preload_status)"
    }
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

function Get-JsonDoubleProperty {
    param(
        [Parameter(Mandatory=$true)]$Object,
        [Parameter(Mandatory=$true)][string]$Name,
        [double]$Default = [double]::NaN
    )
    if ($Object.PSObject.Properties[$Name] -and $null -ne $Object.$Name) {
        return [double]$Object.$Name
    }
    return $Default
}

function Set-ReducedContactClosureGeometry {
    param(
        [Parameter(Mandatory=$true)]$Payload,
        [Parameter(Mandatory=$true)][double]$OverclosureMm
    )
    if ($OverclosureMm -le 0.0) {
        return $false
    }

    $geometry = Ensure-JsonObjectProperty $Payload "derived_geometry_mm"
    $analysis = Ensure-JsonObjectProperty $Payload "analysis_conditions"
    $metadata = Ensure-JsonObjectProperty $Payload "metadata"
    $armour = Ensure-JsonObjectProperty $Payload "armour"

    $innerCenter = Get-JsonDoubleProperty $geometry "inner_armour_center_radius_mm"
    $outerCenter = Get-JsonDoubleProperty $geometry "outer_armour_center_radius_mm"
    $innerWire = Get-JsonDoubleProperty $armour "inner_wire_radius_mm" (Get-JsonDoubleProperty $geometry "inner_armour_wire_radius_mm")
    $outerWire = Get-JsonDoubleProperty $armour "outer_wire_radius_mm" (Get-JsonDoubleProperty $geometry "outer_armour_wire_radius_mm")
    $innerSheathInner = Get-JsonDoubleProperty $geometry "inner_sheath_inner_radius_mm"
    $outerSheathOuter = Get-JsonDoubleProperty $geometry "outer_sheath_outer_radius_mm"

    foreach ($item in @(
        @{ name = "inner_armour_center_radius_mm"; value = $innerCenter },
        @{ name = "outer_armour_center_radius_mm"; value = $outerCenter },
        @{ name = "inner_wire_radius_mm"; value = $innerWire },
        @{ name = "outer_wire_radius_mm"; value = $outerWire },
        @{ name = "inner_sheath_inner_radius_mm"; value = $innerSheathInner },
        @{ name = "outer_sheath_outer_radius_mm"; value = $outerSheathOuter }
    )) {
        if ([double]::IsNaN([double]$item.value)) {
            throw "Cannot apply contact closure geometry; missing $($item.name)."
        }
    }

    # B31 beam elements have contact thickness enabled (Thickness=ON) in SurfaceToSurfaceContactStd.
    # Therefore, to close the contact and generate preload, the solid surfaces must align
    # with the beam centerline center radius minus/plus wire radius plus/minus overclosure.
    $newInnerSheathOuter = $innerCenter + $OverclosureMm
    $newBeddingInner = $innerCenter - $OverclosureMm
    $newBeddingOuter = $outerCenter + $OverclosureMm
    $newOuterSheathInner = $outerCenter - $OverclosureMm

    if ($newInnerSheathOuter -le $innerSheathInner) {
        throw "Contact closure overclosure is too large: inner sheath outer radius would be <= inner radius."
    }
    # Bedding inner and Inner sheath outer may overlap to close the B31 centerline node contact.
    # We skip the overlap check between these layers to allow centerline alignment.
    if ($newBeddingOuter -le $newBeddingInner) {
        throw "Contact closure overclosure is too large: bedding outer radius would be <= bedding inner radius."
    }
    # Outer sheath inner and Bedding outer may overlap to close the B31 centerline node contact.
    # We skip the overlap check between these layers to allow centerline alignment.
    if ($newOuterSheathInner -ge $outerSheathOuter) {
        throw "Contact closure overclosure is too large: outer sheath inner radius would be >= outer radius."
    }

    $original = [pscustomobject]@{
        inner_sheath_outer_radius_mm = Get-JsonDoubleProperty $geometry "inner_sheath_outer_radius_mm"
        inner_armour_outer_radius_mm = Get-JsonDoubleProperty $geometry "inner_armour_outer_radius_mm"
        bedding_outer_radius_mm = Get-JsonDoubleProperty $geometry "bedding_outer_radius_mm"
        outer_sheath_inner_radius_mm = Get-JsonDoubleProperty $geometry "outer_sheath_inner_radius_mm"
    }
    $adjusted = [pscustomobject]@{
        inner_sheath_outer_radius_mm = [double]$newInnerSheathOuter
        inner_armour_outer_radius_mm = [double]$newBeddingInner
        bedding_outer_radius_mm = [double]$newBeddingOuter
        outer_sheath_inner_radius_mm = [double]$newOuterSheathInner
    }

    Set-JsonObjectProperty $geometry "inner_sheath_outer_radius_mm" ([double]$newInnerSheathOuter)
    Set-JsonObjectProperty $geometry "inner_armour_outer_radius_mm" ([double]$newBeddingInner)
    Set-JsonObjectProperty $geometry "bedding_outer_radius_mm" ([double]$newBeddingOuter)
    Set-JsonObjectProperty $geometry "outer_sheath_inner_radius_mm" ([double]$newOuterSheathInner)

    $closure = [pscustomobject]@{
        enabled = $true
        mode = "reduced_geometry_radial_overclosure"
        target_overclosure_mm = [double]$OverclosureMm
        original_radii_mm = $original
        adjusted_radii_mm = $adjusted
        note = "Reduced validation closure only; use Abaqus interference/shrink-fit or calibrated geometry before production research use."
    }
    Set-JsonObjectProperty $analysis "abaqus_contact_closure_overclosure_mm" ([double]$OverclosureMm)
    Set-JsonObjectProperty $analysis "abaqus_contact_closure_mode" "reduced_geometry_radial_overclosure"
    Set-JsonObjectProperty $metadata "contact_closure_overclosure_mm" ([double]$OverclosureMm)
    Set-JsonObjectProperty $metadata "contact_closure_adjustment" $closure
    return $true
}

function New-SmallSmokeJob {
    param(
        [Parameter(Mandatory=$true)][string]$ProjectRoot,
        [Parameter(Mandatory=$true)][string]$SourceJobDir,
        [Parameter(Mandatory=$true)][int]$AxialDivisions,
        [Parameter(Mandatory=$true)][int]$CoreCircumferentialDivisions,
        [Parameter(Mandatory=$true)][int]$ArmourCircumferentialDivisions,
        [Parameter(Mandatory=$true)][double]$EffectiveLengthMm,
        [Parameter(Mandatory=$true)][int]$AbaqusOutputIntervals,
        [Parameter(Mandatory=$true)][bool]$UseMultiStepSmoke,
        [Parameter(Mandatory=$true)][bool]$UseCurveV0,
        [Parameter(Mandatory=$true)][double]$CurveV0CurvatureScale,
        [Parameter(Mandatory=$true)][double]$ContactClosureOverclosureMm
    )

    $jobsRoot = Join-Path $ProjectRoot "jobs\SCLAS_jobs"
    if (-not (Test-Path $jobsRoot)) {
        New-Item -ItemType Directory -Path $jobsRoot -Force | Out-Null
    }
    $jobPrefix = if ($UseCurveV0) { "curve_v0_" } else { "small_smoke_" }
    $smallName = $jobPrefix + (Get-Date -Format "yyyyMMdd_HHmmss")
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
    Set-JsonObjectProperty $analysis "abaqus_multistep_smoke" ([bool]$UseMultiStepSmoke)
    Set-JsonObjectProperty $analysis "abaqus_curve_v0" ([bool]$UseCurveV0)
    Set-JsonObjectProperty $analysis "abaqus_curve_v0_curvature_scale" ([double]$CurveV0CurvatureScale)
    if ($UseCurveV0) {
        Set-JsonObjectProperty $analysis "abaqus_curve_v0_endpoint" $true
        Set-JsonObjectProperty $analysis "abaqus_curve_v0_endpoint_factor" ([double]$CurveV0CurvatureScale)
    } else {
        Set-JsonObjectProperty $analysis "abaqus_curve_v0_endpoint" $false
    }
    if ($analysis.PSObject.Properties["solver_steps"]) {
        $analysis.solver_steps = 25
    }
    $contactClosureApplied = Set-ReducedContactClosureGeometry -Payload $payload -OverclosureMm $ContactClosureOverclosureMm
    Set-JsonObjectProperty $metadata "job_id" $smallName
    Set-JsonObjectProperty $metadata "lab_smoke_source_job" (Split-Path -Leaf $SourceJobDir)
    Set-JsonObjectProperty $metadata "analysis_mode" $(if ($UseCurveV0) { "curve_v0" } else { "small_smoke" })

    $jsonText = $payload | ConvertTo-Json -Depth 100
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($inputPath, $jsonText + [Environment]::NewLine, $utf8NoBom)

    Write-Host "Created reduced smoke job: $smallDir"
    Write-Host "  axial_divisions=$AxialDivisions, core_circ=$CoreCircumferentialDivisions, armour_circ=$ArmourCircumferentialDivisions, effective_length_mm=$EffectiveLengthMm, abaqus_output_intervals=$AbaqusOutputIntervals, multistep_smoke=$UseMultiStepSmoke, curve_v0=$UseCurveV0, endpoint_factor=$CurveV0CurvatureScale, contact_closure_applied=$contactClosureApplied, contact_overclosure_mm=$ContactClosureOverclosureMm"
    return $smallDir
}

$ProjectRoot = Resolve-ProjectRoot
if (-not $JobDir) {
    $JobDir = Find-LatestJobDir $ProjectRoot
}
$SourceJobDir = (Resolve-Path $JobDir).Path
if (($SmallSmoke -or $CurveV0) -and $SkipGeneration) {
    throw "-SmallSmoke/-CurveV0 cannot be combined with -SkipGeneration because the reduced job has no generated .inp yet."
}
if ($ContactClosureOverclosureMm -lt 0.0) {
    throw "-ContactClosureOverclosureMm must be zero or positive."
}
if ($SmallSmoke -or $CurveV0) {
    $JobDir = New-SmallSmokeJob `
        -ProjectRoot $ProjectRoot `
        -SourceJobDir $SourceJobDir `
        -AxialDivisions $SmallAxialDivisions `
        -CoreCircumferentialDivisions $SmallCoreCircumferentialDivisions `
        -ArmourCircumferentialDivisions $SmallArmourCircumferentialDivisions `
        -EffectiveLengthMm $SmallEffectiveLengthMm `
        -AbaqusOutputIntervals $SmallAbaqusOutputIntervals `
        -UseMultiStepSmoke ([bool]$MultiStepSmoke) `
        -UseCurveV0 ([bool]$CurveV0) `
        -CurveV0CurvatureScale $CurveV0CurvatureScale `
        -ContactClosureOverclosureMm $ContactClosureOverclosureMm
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
if ($SmallSmoke -or $CurveV0) {
    Write-Host "Source:  $SourceJobDir"
}
Write-Host "Job:     $JobDir"
Write-Host "Mode:    $(if ($CurveV0 -and $GenerateOnly) { 'curve v0 generate only' } elseif ($CurveV0) { 'curve v0 generate + solver' } elseif ($SmallSmoke -and $GenerateOnly) { 'small smoke generate only' } elseif ($SmallSmoke) { 'small smoke generate + solver' } elseif ($GenerateOnly) { 'generate only' } elseif ($SkipGeneration) { 'solver only' } else { 'generate + solver' })"

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
        Sort-Object LastWriteTime -Descending
    if ($inpCandidates) {
        $inp = $inpCandidates | Select-Object -First 1
        Write-Host "No generated *_mesh.inp or *_mes.inp file was found; using latest .inp: $($inp.Name)" -ForegroundColor Yellow
    } else {
        throw "No Abaqus .inp file was found. Check abaqus_stdout.txt and abaqus_mesh_manifest.json."
    }
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
