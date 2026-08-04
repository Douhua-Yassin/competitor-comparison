. "$PSScriptRoot\common.ps1"
Set-Location $script:ProjectRoot

$python = Join-Path $script:ProjectRoot '.venv\Scripts\python.exe'
$pidFile = Join-Path $script:ProjectRoot 'data\reporting-server.pid'
$stdoutLog = Join-Path $script:ProjectRoot 'data\reporting-server.log'
$stderrLog = Join-Path $script:ProjectRoot 'data\reporting-server-error.log'
$statusUrl = 'http://127.0.0.1:8790/api/status'

function Test-IsReportingProcess($Process) {
    if (-not $Process -or -not $Process.CommandLine) { return $false }
    return (
        $Process.CommandLine -match '(?i)(?:^|\s)-m\s+uvicorn\s+app\.reporting_app:app(?:\s|$)' -and
        $Process.CommandLine -match '(?i)--port\s+8790(?:\s|$)'
    )
}

if (-not (Test-Path -LiteralPath $python)) {
    Show-AppMessage -Title '经营报告数据管理' -Message '尚未完成首次安装，请先运行“首次安装.bat”。' -Icon Warning
    exit 1
}

$listenerProcess = Get-ListeningProcess -Port 8790
if ($listenerProcess) {
    if (-not (Test-IsReportingProcess -Process $listenerProcess)) {
        Show-AppMessage -Title '经营报告数据管理' -Message "8790 端口已被其他程序占用。`n`n$($listenerProcess.CommandLine)" -Icon Error
        exit 1
    }
    if (Test-LocalUrl -Url $statusUrl) {
        if (-not $env:CI) { Start-Process 'http://127.0.0.1:8790/reporting' }
        exit 0
    }
    Stop-Process -Id $listenerProcess.ProcessId -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 800
}

New-Item -ItemType Directory -Path (Join-Path $script:ProjectRoot 'data') -Force | Out-Null
Remove-Item -LiteralPath $pidFile, $stdoutLog, $stderrLog -Force -ErrorAction SilentlyContinue

try {
    $process = Start-Process `
        -FilePath $python `
        -ArgumentList '-m uvicorn app.reporting_app:app --host 127.0.0.1 --port 8790' `
        -WorkingDirectory $script:ProjectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -PassThru
    [System.IO.File]::WriteAllText($pidFile, [string]$process.Id, [System.Text.Encoding]::ASCII)
}
catch {
    Show-AppMessage -Title '经营报告数据管理' -Message ("报告服务启动失败：" + $_.Exception.Message) -Icon Error
    exit 1
}

for ($i = 1; $i -le 45; $i++) {
    if (Test-LocalUrl -Url $statusUrl) {
        if (-not $env:CI) { Start-Process 'http://127.0.0.1:8790/reporting' }
        exit 0
    }
    if ($process.HasExited) { break }
    if ($i -eq 10) { Write-Host '报告服务仍在初始化，请稍候...' }
    Start-Sleep -Seconds 1
}

if (-not $process.HasExited) {
    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
}
Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
$tail = ''
if (Test-Path -LiteralPath $stderrLog) {
    $tail = (Get-Content -LiteralPath $stderrLog -Tail 20 -ErrorAction SilentlyContinue) -join "`n"
}
$message = '报告服务在 45 秒内没有准备完成。'
if ($tail) { $message += "`n`n最近错误：`n$tail" }
Show-AppMessage -Title '经营报告数据管理' -Message $message -Icon Error
exit 1
