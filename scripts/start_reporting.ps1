. "$PSScriptRoot\common.ps1"
Set-Location $script:ProjectRoot

$python = Join-Path $script:ProjectRoot '.venv-lingxing\Scripts\python.exe'
$requirements = Join-Path $script:ProjectRoot 'requirements-lingxing.txt'
$pidFile = Join-Path $script:ProjectRoot 'data\reporting-server.pid'
$stdoutLog = Join-Path $script:ProjectRoot 'data\reporting-server.log'
$stderrLog = Join-Path $script:ProjectRoot 'data\reporting-server-error.log'
$statusUrl = 'http://127.0.0.1:8790/api/status'
$reportUrl = 'http://127.0.0.1:8790/reporting'
$openScript = Join-Path $PSScriptRoot 'open_reporting.ps1'

function Add-LoopbackNoProxy {
    $required = @('127.0.0.1', 'localhost')
    foreach ($name in @('NO_PROXY', 'no_proxy')) {
        $current = [Environment]::GetEnvironmentVariable($name, 'Process')
        $parts = @()
        if ($current) {
            $parts = @($current.Split(',') | ForEach-Object { $_.Trim() } | Where-Object { $_ })
        }
        foreach ($item in $required) {
            if ($parts -notcontains $item) { $parts += $item }
        }
        [Environment]::SetEnvironmentVariable($name, ($parts -join ','), 'Process')
    }
}

function Open-ReportingPage {
    if ($env:CI) { return }
    if (Test-Path -LiteralPath $openScript) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $openScript -Url $reportUrl
    }
    else {
        Start-Process $reportUrl
    }
}

function Test-IsReportingProcess($Process) {
    if (-not $Process -or -not $Process.CommandLine) { return $false }
    return (
        $Process.CommandLine -match '(?i)(?:^|\s)-m\s+uvicorn\s+app\.reporting_app:app(?:\s|$)' -and
        $Process.CommandLine -match '(?i)--port\s+8790(?:\s|$)'
    )
}

Add-LoopbackNoProxy

if (-not (Test-Path -LiteralPath $python)) {
    Show-AppMessage -Title '经营报告' -Message '尚未创建领星专用环境。请先运行“领星接口盘点.bat”，程序不会修改原竞品环境。' -Icon Warning
    exit 1
}

$dependencyCode = 1
$previousPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = 'SilentlyContinue'
    & $python -c "import fastapi, uvicorn, jinja2, httpx, docx, dotenv, lingxingapi_httpx" 2>$null
    $dependencyCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $previousPreference
}
if ($dependencyCode -ne 0) {
    Write-Host '正在安装报告程序依赖……'
    & $python -m pip install --disable-pip-version-check --no-cache-dir -r $requirements
    if ($LASTEXITCODE -ne 0) {
        Show-AppMessage -Title '经营报告' -Message '报告程序依赖安装失败，请查看当前窗口中的错误。' -Icon Error
        exit 1
    }
}

$listenerProcess = Get-ListeningProcess -Port 8790
if ($listenerProcess) {
    if (-not (Test-IsReportingProcess -Process $listenerProcess)) {
        Show-AppMessage -Title '经营报告' -Message "8790 端口已被其他程序占用。`n`n$($listenerProcess.CommandLine)" -Icon Error
        exit 1
    }
    if (Test-LocalUrl -Url $statusUrl) {
        Open-ReportingPage
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
    Show-AppMessage -Title '经营报告' -Message ("报告服务启动失败：" + $_.Exception.Message) -Icon Error
    exit 1
}

for ($i = 1; $i -le 60; $i++) {
    if (Test-LocalUrl -Url $statusUrl) {
        Open-ReportingPage
        exit 0
    }
    if ($process.HasExited) { break }
    if ($i -eq 10) { Write-Host '报告服务仍在初始化，请稍候...' }
    if ($i -eq 30) { Write-Host '首次启动可能正在初始化数据库和文档组件...' }
    Start-Sleep -Seconds 1
}

if (-not $process.HasExited) {
    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
}
Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
$tail = ''
if (Test-Path -LiteralPath $stderrLog) {
    $tail = (Get-Content -LiteralPath $stderrLog -Tail 30 -ErrorAction SilentlyContinue) -join "`n"
}
$message = '报告服务在 60 秒内没有准备完成。'
if ($tail) { $message += "`n`n最近错误：`n$tail" }
Show-AppMessage -Title '经营报告' -Message $message -Icon Error
exit 1
