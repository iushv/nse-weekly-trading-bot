param(
    [ValidateSet("start", "stop", "status", "remove")]
    [string]$Action = "status",
    [string]$TaskName = "TradingBotPaper"
)

$ErrorActionPreference = "Stop"

switch ($Action) {
    "start" {
        Start-ScheduledTask -TaskName $TaskName
        Write-Host "Started task: $TaskName"
    }
    "stop" {
        Stop-ScheduledTask -TaskName $TaskName
        Write-Host "Stopped task: $TaskName"
    }
    "status" {
        $task = Get-ScheduledTask -TaskName $TaskName
        $info = Get-ScheduledTaskInfo -TaskName $TaskName
        Write-Host "Task: $($task.TaskName)"
        Write-Host "State: $($task.State)"
        Write-Host "LastRunTime: $($info.LastRunTime)"
        Write-Host "LastTaskResult: $($info.LastTaskResult)"
        Write-Host "NextRunTime: $($info.NextRunTime)"
    }
    "remove" {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed task: $TaskName"
    }
}
