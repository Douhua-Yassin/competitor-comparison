$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.Net.Http
$script:ProjectRoot = Split-Path -Parent $PSScriptRoot

function Show-AppMessage {
    param(
        [Parameter(Mandatory = $true)][string]$Message,
        [string]$Title = 'Amazon 竞品监控',
        [ValidateSet('Information', 'Warning', 'Error')][string]$Icon = 'Information'
    )

    if ($env:CI) {
        Write-Host $Message
        return
    }

    Add-Type -AssemblyName System.Windows.Forms
    $iconValue = [System.Windows.Forms.MessageBoxIcon]::$Icon
    [void][System.Windows.Forms.MessageBox]::Show(
        $Message,
        $Title,
        [System.Windows.Forms.MessageBoxButtons]::OK,
        $iconValue
    )
}

function New-NoProxyHttpClient {
    $handler = New-Object System.Net.Http.HttpClientHandler
    $handler.UseProxy = $false
    $client = [System.Net.Http.HttpClient]::new($handler)
    $client.Timeout = [TimeSpan]::FromSeconds(3)
    return $client
}

function Get-LocalJson {
    param([Parameter(Mandatory = $true)][string]$Url)

    $client = New-NoProxyHttpClient
    try {
        $raw = $client.GetStringAsync($Url).GetAwaiter().GetResult()
        return $raw | ConvertFrom-Json
    }
    catch {
        return $null
    }
    finally {
        $client.Dispose()
    }
}

function Test-LocalUrl {
    param([Parameter(Mandatory = $true)][string]$Url)

    $client = New-NoProxyHttpClient
    try {
        $response = $client.GetAsync($Url).GetAwaiter().GetResult()
        return $response.IsSuccessStatusCode
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function Get-ListeningProcess {
    param([Parameter(Mandatory = $true)][int]$Port)

    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $listener) {
        return $null
    }

    return Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)" -ErrorAction SilentlyContinue
}

function Test-IsMonitorProcess {
    param($Process)

    if (-not $Process -or -not $Process.CommandLine) {
        return $false
    }

    return (
        $Process.CommandLine -match '(?i)(?:^|\s)-m\s+uvicorn\s+app\.main:app(?:\s|$)' -and
        $Process.CommandLine -match '(?i)--port\s+8787(?:\s|$)'
    )
}
