param(
    [switch]$SkipCompose
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$src = Join-Path $root 'src'
$build = Join-Path $root 'build'
$job = 'stacks-zh-hans-cn-partial'

if (-not $SkipCompose) {
    & python (Join-Path $root 'compose.py') | Out-File -LiteralPath (Join-Path $root 'qa\compose.stdout.json') -Encoding utf8
    if ($LASTEXITCODE -ne 0) {
        throw "compose.py failed with exit code $LASTEXITCODE"
    }
}

if (-not (Test-Path -LiteralPath $build)) {
    New-Item -ItemType Directory -Path $build | Out-Null
}

# Remove only this build's known, reproducible outputs before replay.
foreach ($extension in @('aux','bbl','blg','log','out','pdf','toc','fls')) {
    $candidate = Join-Path $build ($job + '.' + $extension)
    if (Test-Path -LiteralPath $candidate) {
        Remove-Item -LiteralPath $candidate -Force
    }
}

$savedBibInputs = $env:BIBINPUTS
$savedSourceDateEpoch = $env:SOURCE_DATE_EPOCH
$savedForceSourceDate = $env:FORCE_SOURCE_DATE
$savedTimezone = $env:TZ
$env:BIBINPUTS = "$src;$savedBibInputs"
$env:SOURCE_DATE_EPOCH = '1787356800'
$env:FORCE_SOURCE_DATE = '1'
$env:TZ = 'UTC'

function Invoke-XeLaTeX {
    Push-Location $src
    try {
        & xelatex '-interaction=nonstopmode' '-halt-on-error' '-file-line-error' '-recorder' '-no-shell-escape' "-jobname=$job" "-output-directory=$build" 'reader.tex'
        if ($LASTEXITCODE -ne 0) {
            throw "XeLaTeX failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
}

try {
    Invoke-XeLaTeX
    Push-Location $build
    try {
        & bibtex $job
        if ($LASTEXITCODE -ne 0) {
            throw "BibTeX failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
    Invoke-XeLaTeX
    Invoke-XeLaTeX
    Invoke-XeLaTeX
}
finally {
    $env:BIBINPUTS = $savedBibInputs
    $env:SOURCE_DATE_EPOCH = $savedSourceDateEpoch
    $env:FORCE_SOURCE_DATE = $savedForceSourceDate
    $env:TZ = $savedTimezone
}

$pdf = Join-Path $build ($job + '.pdf')
if (-not (Test-Path -LiteralPath $pdf)) {
    throw "Expected PDF was not created: $pdf"
}

Get-Item -LiteralPath $pdf | Select-Object FullName,Length,LastWriteTime
Get-FileHash -LiteralPath $pdf -Algorithm SHA256
