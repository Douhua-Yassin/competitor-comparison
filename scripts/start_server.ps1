. "$PSScriptRoot\common.ps1"
Set-Location $script:ProjectRoot

$python = Join-Path $script:ProjectRoot '.venv\Scripts\python.exe'
$pidFile = Join-Path $script:ProjectRoot 'data\server.pid'
$stdoutLog = Join-Path $script:ProjectRoot 'data\server.log'
$stderrLog = Join-Path $script:ProjectRoot 'data\server-error.log'
$mainFile = Join-Path $script:ProjectRoot 'app\main.py'
$statusUrl = 'http://127.0.0.1:8787/api/status'

if (-not (Test-Path -LiteralPath $python)) {
    Show-AppMessage -Message '尚未完成首次安装，请先运行“首次安装.bat”。' -Icon Warning
    exit 1
}

$listenerProcess = Get-ListeningProcess -Port 8787
if ($listenerProcess) {
    if (-not (Test-IsMonitorProcess -Process $listenerProcess)) {
        Show-AppMessage -Message "8787 端口已被其他程序占用。`n`n$($listenerProcess.CommandLine)" -Icon Error
        exit 1
    }

    if ($listenerProcess.CreationDate -is [datetime]) {
        $processCreated = [datetime]$listenerProcess.CreationDate
    }
    else {
        $processCreated = [System.Management.ManagementDateTimeConverter]::ToDateTime([string]$listenerProcess.CreationDate)
    }
    $codeModified = (Get-Item -LiteralPath $mainFile).LastWriteTime
    $healthy = Test-LocalUrl -Url $statusUrl

    if ($healthy -and $processCreated -ge $codeModified) {
        if (-not $env:CI) {
            Start-Process 'http://127.0.0.1:8787'
        }
        exit 0
    }

    Write-Host '检测到旧版本或异常的本项目服务，正在重新启动...'
    Stop-Process -Id $listenerProcess.ProcessId -Force -ErrorAction Stop
    Start-Sleep -Milliseconds 800
}

New-Item -ItemType Directory -Path (Join-Path $script:ProjectRoot 'data') -Force | Out-Null
Remove-Item -LiteralPath $pidFile, $stdoutLog, $stderrLog -Force -ErrorAction SilentlyContinue

$arguments = '-m uvicorn app.main:app --host 127.0.0.1 --port 8787'
Write-Host '正在后台启动程序服务...'

try {
    $startParameters = @{
        FilePath = $python
        ArgumentList = $arguments
        WorkingDirectory = $script:ProjectRoot
        WindowStyle = 'Hidden'
        RedirectStandardOutput = $stdoutLog
        RedirectStandardError = $stderrLog
        PassThru = $true
    }
    $process = Start-Process @startParameters
    [System.IO.File]::WriteAllText($pidFile, [string]$process.Id, [System.Text.Encoding]::ASCII)
}
catch {
    Show-AppMessage -Message ("程序服务启动失败：" + $_.Exception.Message) -Icon Error
    exit 1
}

for ($i = 1; $i -le 45; $i++) {
    if (Test-LocalUrl -Url $statusUrl) {
        if (-not $env:CI) {
            Start-Process 'http://127.0.0.1:8787'
        }
        exit 0
    }

    if ($process.HasExited) {
        break
    }

    if ($i -eq 10) { Write-Host '服务仍在启动，请稍候...' }
    if ($i -eq 25) { Write-Host '正在等待首次数据库初始化完成...' }
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
$message = '服务在 45 秒内没有准备完成。'
if ($tail) {
    $message += "`n`n最近错误：`n$tail"
}
Show-AppMessage -Message $message -Icon Error
exit 1
