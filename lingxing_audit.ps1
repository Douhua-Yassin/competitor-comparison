$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$OptionalRequirements = Join-Path $Root 'requirements-lingxing.txt'

function Show-Message([string]$Text) {
    Add-Type -AssemblyName System.Windows.Forms
    [void][System.Windows.Forms.MessageBox]::Show($Text, '领星接口盘点')
}

if (-not (Test-Path $Python)) {
    Show-Message '请先运行“首次安装.bat”。'
    exit 1
}

$VersionText = (& $Python -c "import sys; print('%d.%d' % sys.version_info[:2])").Trim()
if ([version]$VersionText -lt [version]'3.10') {
    Show-Message ("领星接口盘点需要 Python 3.10 或更高版本。当前虚拟环境版本：{0}。原有竞品监控不受影响。" -f $VersionText)
    exit 1
}

Set-Location $Root
& $Python -c "import lingxingapi_httpx" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host '正在安装领星接口盘点依赖……'
    & $Python -m pip install --disable-pip-version-check --no-cache-dir -r $OptionalRequirements
    if ($LASTEXITCODE -ne 0) {
        Show-Message '领星接口盘点依赖安装失败，请保留命令窗口中的错误信息。'
        exit 1
    }
}

& $Python -m app.lingxing_audit.cli
$Code = $LASTEXITCODE
if ($Code -eq 0) {
    $Latest = Join-Path $Root 'data\lingxing_audit\latest.txt'
    if (Test-Path $Latest) {
        $RunId = (Get-Content $Latest -Raw).Trim()
        $Report = Join-Path $Root ("data\lingxing_audit\{0}\audit-report.md" -f $RunId)
        if (Test-Path $Report) {
            Start-Process notepad.exe -ArgumentList $Report
        }
    }
}
else {
    Read-Host '盘点未完成。请保留上方错误信息并按 Enter 关闭'
}
exit $Code
