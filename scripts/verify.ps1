$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw ".venv가 없습니다. 먼저 install.ps1을 실행하세요."
}

& $Python -m pytest
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

& (Join-Path $PSScriptRoot "privacy-audit.ps1") -Root $ProjectRoot
exit $LASTEXITCODE
