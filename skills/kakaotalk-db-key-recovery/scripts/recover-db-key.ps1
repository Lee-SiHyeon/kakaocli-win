param(
    [string]$Database,
    [ValidateSet(1, 2, 4, 8, 16)]
    [int]$Stride = 4,
    [ValidateRange(1, 3600)]
    [double]$Timeout = 120,
    [switch]$NoStore,
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\.."))
)

$ErrorActionPreference = "Stop"
$Launcher = Join-Path $ProjectRoot "kakaocli.cmd"

if (-not (Test-Path -LiteralPath $Launcher)) {
    throw "kakaocli.cmd를 찾지 못했습니다. 먼저 install.ps1을 실행하세요."
}

$Arguments = @("--json", "recover-key", "--stride", "$Stride", "--timeout", "$Timeout")
if ($Database) {
    $ResolvedDatabase = (Resolve-Path -LiteralPath $Database).Path
    $Arguments += @("--db", $ResolvedDatabase)
}
if ($NoStore) {
    $Arguments += "--no-store"
}

& $Launcher @Arguments
exit $LASTEXITCODE
