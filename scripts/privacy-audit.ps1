param(
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot ".."))
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path -LiteralPath $Root).Path
$ForbiddenFiles = @(".env", "keys.json")
$ForbiddenExtensions = @(".edb", ".db", ".sqlite", ".sqlite3", ".pyc", ".pfx", ".p12")
$TextExtensions = @(".py", ".ps1", ".cmd", ".md", ".toml", ".yaml", ".yml", ".json", ".txt")
$Patterns = [ordered]@{
    "Windows user path" = 'C:\\Users\\[^\\\s]+'
    "GitHub token" = '(ghp_|github_pat_)[A-Za-z0-9_]+'
    "API secret" = '(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)\s*[:=]\s*["''][^"'']{8,}["'']'
    "Private key" = '-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----'
}

$Findings = [System.Collections.Generic.List[string]]::new()
$Files = Get-ChildItem -LiteralPath $Root -Recurse -File | Where-Object {
    $_.FullName -notmatch '[\\/]\.git[\\/]' -and
    $_.FullName -notmatch '[\\/](\.venv|__pycache__|\.pytest_cache|dist|build)[\\/]'
}

foreach ($File in $Files) {
    if ($ForbiddenFiles -contains $File.Name -or $ForbiddenExtensions -contains $File.Extension.ToLowerInvariant()) {
        $Findings.Add("금지 파일: $($File.FullName.Substring($Root.Length + 1))")
        continue
    }
    if ($TextExtensions -notcontains $File.Extension.ToLowerInvariant()) {
        continue
    }
    if ($File.FullName -eq $MyInvocation.MyCommand.Path) {
        continue
    }
    $Content = Get-Content -Raw -LiteralPath $File.FullName
    foreach ($Entry in $Patterns.GetEnumerator()) {
        if ($Content -match $Entry.Value) {
            $Findings.Add("$($Entry.Key): $($File.FullName.Substring($Root.Length + 1))")
        }
    }
}

if ($Findings.Count -gt 0) {
    $Findings | Sort-Object -Unique | ForEach-Object { Write-Error $_ }
    exit 1
}

Write-Host "개인정보/비밀정보 사전 점검 통과 ($($Files.Count)개 파일 검사)"
