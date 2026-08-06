. "$PSScriptRoot\common.ps1"
Set-Location $script:ProjectRoot

$pidFile = Join-Path $script:ProjectRoot 'data\reporting-server.pid'

function Test-IsReportingProcess($Process) {
    if (-not $Process -or -not $Process.CommandLine) { return $false }
    return (
        $Process.CommandLine -match '(?i)(?:^|\s)-m\s+uvicorn\s+app\.reporting_app:app(?:\s|$)' -and
        $Process.CommandLine -match '(?i)--port\s+8790(?:\s|$)'
    )
}

$process = Get-ListeningProcess -Port 8790
if (-not $process) {
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    Show-AppMessage -Title '经营报告数据管理' -Message '报告程序当前没有运行。'
    exit 0
}

if (-not (Test-IsReportingProcess -Process $process)) {
    Show-AppMessage -Title '经营报告数据管理' -Message "8790 端口不是本项目报告服务，未执行停止。`n`n$($process.CommandLine)" -Icon Error
    exit 1
}

try {
    Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Milliseconds 250
        if (-not (Get-ListeningProcess -Port 8790)) { break }
    }
    if (Get-ListeningProcess -Port 8790) {
        throw '8790 端口仍在监听'
    }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    Show-AppMessage -Title '经营报告数据管理' -Message '报告程序已经停止。竞品监控和 Chrome 不受影响。'
    exit 0
}
catch {
    Show-AppMessage -Title '经营报告数据管理' -Message ("停止报告服务失败：" + $_.Exception.Message) -Icon Error
    exit 1
}
