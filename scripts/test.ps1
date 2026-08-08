[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PytestArgs
)

$ErrorActionPreference = "Stop"

if (-not $env:OPEN_SIGNAL_TEST_DATABASE_URL) {
    $env:OPEN_SIGNAL_TEST_DATABASE_URL = [Environment]::GetEnvironmentVariable(
        "OPEN_SIGNAL_TEST_DATABASE_URL",
        "User"
    )
}
if (-not $env:OPEN_SIGNAL_TEST_BRANCH_ID) {
    $env:OPEN_SIGNAL_TEST_BRANCH_ID = [Environment]::GetEnvironmentVariable(
        "OPEN_SIGNAL_TEST_BRANCH_ID",
        "User"
    )
}
if (-not $env:OPEN_SIGNAL_TEST_DATABASE_URL) {
    throw "OPEN_SIGNAL_TEST_DATABASE_URL is not configured"
}

$target = [Uri]$env:OPEN_SIGNAL_TEST_DATABASE_URL
$databaseName = $target.AbsolutePath.TrimStart("/")
Write-Host "Test database: $($target.Host)/$databaseName"
if ($env:OPEN_SIGNAL_TEST_BRANCH_ID) {
    Write-Host "Expected Neon branch: $env:OPEN_SIGNAL_TEST_BRANCH_ID"
}

if (-not $PytestArgs -or $PytestArgs.Count -eq 0) {
    $PytestArgs = @("apps/worker/tests", "-q")
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $repoRoot
try {
    & python -m pytest @PytestArgs
    if ($LASTEXITCODE -ne 0) {
        throw "pytest failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
