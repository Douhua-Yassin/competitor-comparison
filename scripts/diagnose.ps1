. "$PSScriptRoot\common.ps1"
Set-Location $script:ProjectRoot

$python = Join-Path $script:ProjectRoot '.venv\Scripts\python.exe'
$chrome = Join-Path $env:LOCALAPPDATA 'Google\Chrome\Application\chrome.exe'
$defaultProfile = Join-Path $env:LOCALAPPDATA 'Google\Chrome\User Data\Default'

Write-Host '===== Amazon 竞品监控故障检查 ====='
Write-Host ''

Write-Host '[1/10] Python 与虚拟环境'
if (Test-Path -LiteralPath $python) {
    & $python --version
}
else {
    Write-Host '未找到 .venv，请先运行“首次安装.bat”。'
}
Write-Host ''

Write-Host '[2/10] Python 依赖版本'
if (Test-Path -LiteralPath $python) {
    & $python -c "import importlib.metadata as m; import fastapi,uvicorn,jinja2,openpyxl,playwright,bs4; print('依赖导入正常'); print('Playwright=' + m.version('playwright'))"
}
Write-Host ''

Write-Host '[3/10] 产品输入表'
if (Test-Path -LiteralPath (Join-Path $script:ProjectRoot '产品输入表.xlsx')) {
    Write-Host '产品输入表.xlsx 存在'
}
else {
    Write-Host '缺少 产品输入表.xlsx'
}
Write-Host ''

Write-Host '[4/10] SQLite 数据库'
if (Test-Path -LiteralPath (Join-Path $script:ProjectRoot 'data\monitor.db')) {
    Write-Host 'data\monitor.db 存在'
}
else {
    Write-Host '数据库尚未生成，首次启动后会创建。'
}
Write-Host ''

Write-Host '[5/10] Google Chrome'
if (Test-Path -LiteralPath $chrome) {
    Write-Host "Chrome 存在：$chrome"
}
else {
    Write-Host '未在用户目录找到 Chrome。'
}
Write-Host ''

Write-Host '[6/10] Chrome Default 配置'
if (Test-Path -LiteralPath $defaultProfile) {
    Write-Host 'Default 配置存在'
}
else {
    Write-Host '未找到 Chrome Default 配置。'
}
Write-Host ''

Write-Host '[7/10] 插件浏览器 9222 端口'
$cdp = Get-LocalJson -Url 'http://127.0.0.1:9222/json/version'
if ($cdp -and $cdp.Browser -match 'Chrome|Chromium' -and $cdp.webSocketDebuggerUrl) {
    Write-Host ("9222 正常：" + $cdp.Browser)
    Write-Host ("WebSocket：" + $cdp.webSocketDebuggerUrl)
}
else {
    Write-Host '9222 未启动或不是有效 Chrome 调试接口。'
}
Write-Host ''

Write-Host '[8/10] Playwright 实际 CDP 连接'
if ((Test-Path -LiteralPath $python) -and $cdp) {
    & $python -m app.cdp_probe
}
else {
    Write-Host '跳过：虚拟环境或 9222 未准备好。'
}
Write-Host ''

Write-Host '[9/10] Web 服务 8787 端口'
if (Test-LocalUrl -Url 'http://127.0.0.1:8787/api/status') {
    Write-Host '8787 正常：HTTP 200'
}
else {
    Write-Host '8787 未启动。'
    if (Test-Path -LiteralPath (Join-Path $script:ProjectRoot 'data\server-error.log')) {
        Write-Host '可查看：data\server-error.log'
    }
}
Write-Host ''

Write-Host '[10/10] 后台服务进程'
$serverProcess = Get-ListeningProcess -Port 8787
if ($serverProcess) {
    $serverProcess | Format-List ProcessId, ExecutablePath, CommandLine, CreationDate
}
else {
    Write-Host '8787 没有监听进程。'
}
Write-Host ''
Write-Host '检查结束。本文件不会抓取商品，也不会修改数据库。'

if (-not $env:CI) {
    Read-Host '按 Enter 键关闭'
}
