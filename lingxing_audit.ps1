$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvRoot = Join-Path $Root '.venv-lingxing'
$Python = Join-Path $VenvRoot 'Scripts\python.exe'
$OptionalRequirements = Join-Path $Root 'requirements-lingxing.txt'

function Show-Message([string]$Text) {
    if ($env:CI -eq '1') {
        Write-Host $Text
        return
    }
    Add-Type -AssemblyName System.Windows.Forms
    [void][System.Windows.Forms.MessageBox]::Show($Text, '领星接口盘点')
}

function Test-Python311([string]$Executable, [string[]]$PrefixArguments = @()) {
    try {
        $Arguments = @($PrefixArguments) + @('-c', "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)")
        & $Executable @Arguments 2>$null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

function New-LingxingEnvironment {
    Write-Host '正在创建领星专用 Python 3.11 环境：.venv-lingxing'

    if ($env:LINGXING_PYTHON) {
        if (-not (Test-Path $env:LINGXING_PYTHON)) {
            throw "LINGXING_PYTHON 指向的文件不存在：$env:LINGXING_PYTHON"
        }
        if (-not (Test-Python311 $env:LINGXING_PYTHON)) {
            throw 'LINGXING_PYTHON 必须指向 Python 3.11。'
        }
        & $env:LINGXING_PYTHON -m venv $VenvRoot
        return
    }

    $PyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($PyLauncher -and (Test-Python311 $PyLauncher.Source @('-3.11'))) {
        & $PyLauncher.Source -3.11 -m venv $VenvRoot
        return
    }

    $Candidates = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'),
        'C:\Program Files\Python311\python.exe',
        'C:\Python311\python.exe'
    )
    foreach ($Candidate in $Candidates) {
        if ((Test-Path $Candidate) -and (Test-Python311 $Candidate)) {
            & $Candidate -m venv $VenvRoot
            return
        }
    }

    throw @'
未找到 Python 3.11。原竞品程序的 Python 3.8 环境不会被修改。
请先在 PowerShell 执行：
winget install -e --id Python.Python.3.11
安装完成后关闭并重新打开 PowerShell，再双击“领星接口盘点.bat”。
'@
}

Set-Location $Root

if (-not (Test-Path $Python)) {
    try {
        New-LingxingEnvironment
    }
    catch {
        Show-Message $_.Exception.Message
        Write-Host $_.Exception.Message
        exit 1
    }
}

$VersionText = (& $Python -c "import sys; print('%d.%d' % sys.version_info[:2])").Trim()
if ($VersionText -ne '3.11') {
    Show-Message (".venv-lingxing 版本不正确：Python {0}。请删除该目录后重新运行，本程序固定使用 Python 3.11。" -f $VersionText)
    exit 1
}

$DependencyCheckCode = 1
$PreviousErrorActionPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = 'SilentlyContinue'
    & $Python -c "import importlib.metadata as m; import dotenv, lingxingapi_httpx; raise SystemExit(0 if m.version('lingxingapi-httpx') == '0.1.5' else 1)" 2>$null
    $DependencyCheckCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $PreviousErrorActionPreference
}

if ($DependencyCheckCode -ne 0) {
    Write-Host '正在安装领星接口盘点依赖……'
    & $Python -m pip install --disable-pip-version-check --no-cache-dir -r $OptionalRequirements
    if ($LASTEXITCODE -ne 0) {
        Show-Message '领星接口盘点依赖安装失败，请保留命令窗口中的错误信息。'
        exit 1
    }
}

if ($env:LINGXING_AUDIT_SETUP_ONLY -eq '1') {
    Write-Host '领星专用 Python 3.11 环境已准备完成。'
    exit 0
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
