. "$PSScriptRoot\common.ps1"
Set-Location $script:ProjectRoot

$python = Join-Path $script:ProjectRoot '.venv\Scripts\python.exe'

try {
    if (-not (Test-Path -LiteralPath $python)) {
        Write-Host '正在创建 Python 虚拟环境...'
        & py -m venv (Join-Path $script:ProjectRoot '.venv')
        if ($LASTEXITCODE -ne 0) {
            throw "创建虚拟环境失败，退出码：$LASTEXITCODE"
        }
    }

    Write-Host '当前 Python 版本：'
    & $python --version
    if ($LASTEXITCODE -ne 0) {
        throw '无法运行虚拟环境中的 Python。'
    }

    Write-Host ''
    Write-Host '正在安装程序依赖...'
    & $python -m pip install --disable-pip-version-check --no-cache-dir -r (Join-Path $script:ProjectRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) {
        throw "依赖安装失败，退出码：$LASTEXITCODE"
    }

    Show-AppMessage -Message '首次安装完成。以后日常使用时，只需运行“启动插件浏览器.bat”和“启动程序.bat”。'
    exit 0
}
catch {
    Show-AppMessage -Message ("首次安装失败：`n`n" + $_.Exception.Message) -Icon Error
    exit 1
}
