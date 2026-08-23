param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\.."))
)

$ErrorActionPreference = "Stop"
$Launcher = Join-Path $ProjectRoot "kakaocli.cmd"

if (-not (Test-Path -LiteralPath $Launcher)) {
    throw "kakaocli.cmd를 찾지 못했습니다: $Launcher"
}

$Raw = & $Launcher --json doctor
if ($LASTEXITCODE -ne 0) {
    throw "kakaocli doctor 실행에 실패했습니다."
}

$Report = $Raw | ConvertFrom-Json
[ordered]@{
    ok = [bool]$Report.ok
    installed = [bool]$Report.installed
    running = [bool]$Report.running
    main_window_found = [bool]$Report.main_window_found
    open_room_count = @($Report.open_rooms).Count
    next = $Report.next
} | ConvertTo-Json
