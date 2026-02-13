param(
    [string]$BotRoot = "",
    [int]$RestartDelaySeconds = 15,
    [switch]$RunOnce
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

function Write-RunnerLog {
    param(
        [string]$Message,
        [string]$LogPath
    )
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $LogPath -Value "[$stamp] $Message"
}

function Load-DotEnv {
    param([string]$EnvFile)
    if (-not (Test-Path $EnvFile)) {
        return
    }

    Get-Content $EnvFile | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            return
        }
        $pair = $line -split "=", 2
        if ($pair.Length -ne 2) {
            return
        }
        $name = $pair[0].Trim()
        $value = $pair[1].Trim().Trim("'").Trim('"')
        if ($name) {
            [System.Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}

$root = Resolve-BotRoot -InputRoot $BotRoot
Set-Location $root

$logsDir = Join-Path $root "logs"
if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir | Out-Null
}
$runnerLog = Join-Path $logsDir "windows_runner.log"

Load-DotEnv -EnvFile (Join-Path $root ".env")

# Hard safety guardrails for this runner: paper only, no live arming.
$env:ENVIRONMENT = "paper"
$env:LIVE_ORDER_EXECUTION_ENABLED = "0"
$env:LIVE_ORDER_FORCE_ACK = ""

$pythonExe = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    $pythonExe = "python"
}

$mainScript = Join-Path $root "main.py"
if (-not (Test-Path $mainScript)) {
    throw "main.py not found at $mainScript"
}

Write-RunnerLog -Message "Runner started. Root=$root Python=$pythonExe RunOnce=$RunOnce" -LogPath $runnerLog

while ($true) {
    try {
        Write-RunnerLog -Message "Launching paper bot process" -LogPath $runnerLog
        & $pythonExe $mainScript --mode paper
        $exitCode = $LASTEXITCODE
        Write-RunnerLog -Message "Bot exited with code $exitCode" -LogPath $runnerLog
    } catch {
        Write-RunnerLog -Message ("Runner exception: " + $_.Exception.Message) -LogPath $runnerLog
    }

    if ($RunOnce) {
        break
    }

    Start-Sleep -Seconds ([Math]::Max(5, $RestartDelaySeconds))
}

Write-RunnerLog -Message "Runner stopped" -LogPath $runnerLog
