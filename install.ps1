$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $ProjectDir ".venv"

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python Launcher(py.exe)를 찾지 못했습니다. Python 3.10 이상을 설치하세요."
}

py -3 -m venv $VenvDir
& (Join-Path $VenvDir "Scripts\python.exe") -m pip install --upgrade pip
& (Join-Path $VenvDir "Scripts\python.exe") -m pip install -e $ProjectDir

$Launcher = Join-Path $ProjectDir "kakaocli.cmd"
Write-Host "설치 완료"
Write-Host "다음 명령으로 점검하세요:"
Write-Host "  $Launcher doctor"

