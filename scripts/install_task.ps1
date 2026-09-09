# Registers (or updates) the daily Windows scheduled task. Run once from PowerShell:
#   powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1 [-Time 08:00]
# Remove with:  Unregister-ScheduledTask -TaskName "JobAgent Daily Search" -Confirm:$false
param([string]$Time = "08:00", [string]$TaskName = "JobAgent Daily Search")
$root = Split-Path -Parent $PSScriptRoot
$wrapper = Join-Path $root "scripts\run_search_task.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$wrapper`"" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "Job Agent: discover, filter and score new jobs; report to data\logs" -Force | Out-Null
$task = Get-ScheduledTask -TaskName $TaskName
Write-Host "Registered '$TaskName' (state: $($task.State)). Next run: $((Get-ScheduledTaskInfo -TaskName $TaskName).NextRunTime)"
Write-Host "If the computer is off at $Time the run starts as soon as it is back on and you are logged in."
