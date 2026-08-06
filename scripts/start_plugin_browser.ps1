. "$PSScriptRoot\common.ps1"
Set-Location $script:ProjectRoot

function Get-CdpInfo {
    $value = Get-LocalJson -Url 'http://127.0.0.1:9222/json/version'
    if (
        $value -and
        $value.Browser -match 'Chrome|Chromium' -and
        $value.webSocketDebuggerUrl
    ) {
        return $value
    }
    return $null
}

$chromeCandidates = New-Object System.Collections.Generic.List[string]
if ($env:APP_CHROME_PATH) { $chromeCandidates.Add($env:APP_CHROME_PATH) }
if ($env:LOCALAPPDATA) { $chromeCandidates.Add((Join-Path $env:LOCALAPPDATA 'Google\Chrome\Application\chrome.exe')) }
if ($env:ProgramFiles) { $chromeCandidates.Add((Join-Path $env:ProgramFiles 'Google\Chrome\Application\chrome.exe')) }
if (${env:ProgramFiles(x86)}) { $chromeCandidates.Add((Join-Path ${env:ProgramFiles(x86)} 'Google\Chrome\Application\chrome.exe')) }

$chrome = $chromeCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $chrome) {
    Show-AppMessage -Message '未找到 Google Chrome。' -Icon Error
    exit 1
}

$cdp = Get-CdpInfo
if ($cdp) {
    Show-AppMessage -Message '插件浏览器已经启动，9222 端口可用。请保持 Chrome 开启。'
    exit 0
}

$listener = Get-ListeningProcess -Port 9222
if ($listener) {
    Show-AppMessage -Message "9222 端口已被占用，但没有返回有效的 Chrome 调试信息。`n`n$($listener.CommandLine)" -Icon Error
    exit 1
}

$userDataDir = if ($env:APP_CHROME_USER_DATA_DIR) {
    $env:APP_CHROME_USER_DATA_DIR
}
else {
    Join-Path $env:LOCALAPPDATA 'Google\Chrome\User Data'
}

$usingDefaultProfile = -not $env:APP_CHROME_USER_DATA_DIR
$existingChrome = Get-Process chrome -ErrorAction SilentlyContinue
if ($usingDefaultProfile -and $existingChrome) {
    Show-AppMessage -Message "当前已有 Chrome 正在运行，因此无法给 Default 配置追加 9222 调试端口。`n`n请保存浏览器中的工作，完全退出所有 Chrome，再重新运行“启动插件浏览器.bat”。" -Icon Warning
    exit 2
}

New-Item -ItemType Directory -Path $userDataDir -Force | Out-Null
$arguments = @(
    '--remote-debugging-address=127.0.0.1',
    '--remote-debugging-port=9222',
    "--user-data-dir=`"$userDataDir`"",
    '--no-first-run'
)
if ($usingDefaultProfile) {
    $arguments += '--profile-directory=Default'
}

Write-Host '正在启动插件浏览器...'
try {
    $process = Start-Process -FilePath $chrome -ArgumentList $arguments -PassThru
}
catch {
    Show-AppMessage -Message ("Chrome 启动失败：" + $_.Exception.Message) -Icon Error
    exit 1
}

for ($i = 1; $i -le 30; $i++) {
    $cdp = Get-CdpInfo
    if ($cdp) {
        Show-AppMessage -Message '插件浏览器启动成功。请保持 Chrome 开启。'
        exit 0
    }
    if ($process.HasExited) {
        break
    }
    Start-Sleep -Seconds 1
}

Show-AppMessage -Message 'Chrome 已打开，但 9222 在 30 秒内没有返回有效的调试信息。请运行“故障检查.bat”。' -Icon Error
exit 1
