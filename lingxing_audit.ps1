$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root '.venv\Scripts\python.exe'

if (-not (Test-Path $Python)) {
    Add-Type -AssemblyName System.Windows.Forms
    [void][System.Windows.Forms.MessageBox]::Show('请先运行“首次安装.bat”。', '领星接口盘点')
    exit 1
}

Set-Location $Root
& $Python -m app.lingxing_audit.cli
$Code = $LASTEXITCODE
if ($Code -eq 0) {
    $Latest = Join-Path $Root 'data\lingxing_audit\latest.txt'
    if (Test-Path $Latest) {
        $RunId = (Get-Content $Latest -Raw).Trim()
        $Report = Join-Path $Root ("data\lingxing_audit\{0}\audit-report.md" -f $RunId)
        if (Test-Path $Report) { Start-Process notepad.exe -ArgumentList $Report }
    }
}
else {
    Read-Host '盘点未完成。请保留上方错误信息并按 Enter 关闭'
}
exit $Code
