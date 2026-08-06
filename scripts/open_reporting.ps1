param(
    [string]$Url = 'http://127.0.0.1:8790/reporting'
)

. "$PSScriptRoot\common.ps1"
Set-Location $script:ProjectRoot

$profileDir = Join-Path $script:ProjectRoot 'data\reporting-browser-profile'
New-Item -ItemType Directory -Path $profileDir -Force | Out-Null

$stamp = [DateTimeOffset]::Now.ToUnixTimeSeconds()
$separator = if ($Url.Contains('?')) { '&' } else { '?' }
$targetUrl = "$Url${separator}startup=$stamp"

$candidates = @(
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:LOCALAPPDATA\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)
$browser = $candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1

if (-not $browser) {
    Start-Process $targetUrl
    exit 0
}

$arguments = @(
    "--user-data-dir=$profileDir",
    '--no-proxy-server',
    '--disable-extensions',
    '--no-first-run',
    '--no-default-browser-check',
    "--app=$targetUrl"
)

try {
    Start-Process -FilePath $browser -ArgumentList $arguments | Out-Null
}
catch {
    Start-Process $targetUrl
}
