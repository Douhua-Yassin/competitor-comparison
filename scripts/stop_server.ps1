. "$PSScriptRoot\common.ps1"
Set-Location $script:ProjectRoot

$pidFile = Join-Path $script:ProjectRoot 'data\server.pid'
$listenerProcess = Get-ListeningProcess -Port 8787
$pidProcess = $null

if (Test-Path -LiteralPath $pidFile) {
    $rawPid = (Get-Content -LiteralPath $pidFile -Raw).Trim()
    if ($rawPid -match '^\d+$') {
        $pidProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $rawPid" -ErrorAction SilentlyContinue
    }
}

$target = if ($listenerProcess) { $listenerProcess } else { $pidProcess }

if (-not $target) {
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    Show-AppMessage -Message '监控程序当前没有运行。'
    exit 0
}

if (-not (Test-IsMonitorProcess -Process $target)) {
    $details = "PID $($target.ProcessId) 正在占用 8787，但命令行不属于本监控程序。`n`n$($target.CommandLine)"
    Show-AppMessage -Message $details -Icon Error
    exit 1
}

try {
    Stop-Process -Id $target.ProcessId -Force -ErrorAction Stop
    Start-Sleep -Milliseconds 500
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    Show-AppMessage -Message '监控程序已经停止。Chrome 和卖家精灵仍保持开启。'
    exit 0
}
catch {
    Show-AppMessage -Message ("无法停止监控程序：" + $_.Exception.Message) -Icon Error
    exit 1
}
