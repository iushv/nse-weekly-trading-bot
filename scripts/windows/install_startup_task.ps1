param(
    [string]$TaskName = "TradingBotPaper",
    [string]$BotRoot = "",
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

$root = Resolve-BotRoot -InputRoot $BotRoot
$runner = Join-Path $root "scripts\windows\run_paper_bot.ps1"
if (-not (Test-Path $runner)) {
    throw "Runner script missing: $runner"
}

$userId = "$env:USERDOMAIN\$env:USERNAME"
$actionArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$runner`" -BotRoot `"$root`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $actionArgs

$triggers = @(
    (New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME)
)
if ($IncludeStartupTrigger) {
    $triggers += (New-ScheduledTaskTrigger -AtStartup)
}

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 3650)

$principal = New-ScheduledTaskPrincipal `
    -UserId $userId `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $triggers `
    -Settings $settings `
    -Principal $principal `
    -Description "Auto-start trading bot paper runner with auto-restart safety." `
    -Force | Out-Null

Write-Host "Scheduled task '$TaskName' installed for user $userId"
Write-Host "Bot root: $root"
Write-Host "Runner: $runner"
