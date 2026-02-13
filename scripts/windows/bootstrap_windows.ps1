param(
    [string]$BotRoot = "",
    [string]$TaskName = "TradingBotPaper",
    [switch]$SkipTaskInstall,
    [switch]$IncludeStartupTrigger
)

$ErrorActionPreference = "Stop"

function Resolve-BotRoot {
    param([string]$InputRoot)
    if ($InputRoot -and (Test-Path $InputRoot)) {
        return (Resolve-Path $InputRoot).Path
    }

    $scriptRoot = Split-Path -Parent $PSCommandPath
    return (Resolve-Path (Join-Path $scriptRoot "..\..")).Path
}

function Set-OrAddEnvValue {
    param(
        [string]$EnvPath,
        [string]$Name,
        [string]$Value
    )

    if (-not (Test-Path $EnvPath)) {
        Set-Content -Path $EnvPath -Value "$Name=$Value"
        return
    }

    $lines = Get-Content -Path $EnvPath
    $pattern = "^\s*{0}\s*=" -f [Regex]::Escape($Name)
    $matched = $false
    $updated = foreach ($line in $lines) {
        if ($line -match $pattern) {
            $matched = $true
            "$Name=$Value"
        } else {
            $line
        }
    }
    if (-not $matched) {
        $updated += "$Name=$Value"
    }
    Set-Content -Path $EnvPath -Value $updated
}

function Invoke-PythonChecked {
    param(
        [string]$PythonExe,
        [string[]]$Arguments
    )

    & $PythonExe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed: $PythonExe $($Arguments -join ' ')"
    }
}

$root = Resolve-BotRoot -InputRoot $BotRoot
Set-Location $root

Write-Host "Bootstrap root: $root"

$venvDir = Join-Path $root ".venv"
$pythonExe = Join-Path $venvDir "Scripts\python.exe"

if (-not (Test-Path $pythonExe)) {
    Write-Host "Creating virtual environment..."
    py -3 -m venv $venvDir
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create venv with py -3"
    }
}

if (-not (Test-Path $pythonExe)) {
    throw "Python executable not found in .venv: $pythonExe"
}

Write-Host "Installing dependencies..."
Invoke-PythonChecked -PythonExe $pythonExe -Arguments @("-m", "pip", "install", "--upgrade", "pip")
Invoke-PythonChecked -PythonExe $pythonExe -Arguments @("-m", "pip", "install", "-r", "requirements.txt")

$envPath = Join-Path $root ".env"
$envExamplePath = Join-Path $root ".env.example"
if (-not (Test-Path $envPath)) {
    if (-not (Test-Path $envExamplePath)) {
        throw ".env.example not found at $envExamplePath"
    }
    Copy-Item -Path $envExamplePath -Destination $envPath
    Write-Host "Created .env from .env.example"
}

# Enforce safe paper defaults in local .env for bootstrap.
Set-OrAddEnvValue -EnvPath $envPath -Name "ENVIRONMENT" -Value "paper"
Set-OrAddEnvValue -EnvPath $envPath -Name "LIVE_ORDER_EXECUTION_ENABLED" -Value "0"
Set-OrAddEnvValue -EnvPath $envPath -Name "LIVE_ORDER_FORCE_ACK" -Value ""
Set-OrAddEnvValue -EnvPath $envPath -Name "AUTO_RESUME_ENABLED" -Value "1"
Set-OrAddEnvValue -EnvPath $envPath -Name "AUTO_RESUME_INTERVAL_SECONDS" -Value "60"

Write-Host "Initializing database schema..."
Invoke-PythonChecked -PythonExe $pythonExe -Arguments @("-c", "from trading_bot.data.storage.database import db; db.init_db()")

if (-not $SkipTaskInstall) {
    $installer = Join-Path $root "scripts\windows\install_startup_task.ps1"
    $manager = Join-Path $root "scripts\windows\manage_startup_task.ps1"
    if (-not (Test-Path $installer)) {
        throw "Task installer not found: $installer"
    }
    if (-not (Test-Path $manager)) {
        throw "Task manager not found: $manager"
    }

    $installArgs = @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        $installer,
        "-TaskName",
        $TaskName,
        "-BotRoot",
        $root
    )
    if ($IncludeStartupTrigger) {
        $installArgs += "-IncludeStartupTrigger"
    }

    Write-Host "Installing scheduled task..."
    & powershell.exe @installArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install scheduled task $TaskName"
    }

    Write-Host "Starting scheduled task..."
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $manager -Action start -TaskName $TaskName
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to start scheduled task $TaskName"
    }

    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $manager -Action status -TaskName $TaskName
}

Write-Host ""
Write-Host "Bootstrap complete."
Write-Host "Runner log: $root\logs\windows_runner.log"
Write-Host "Heartbeat:  $root\control\heartbeat.json"
