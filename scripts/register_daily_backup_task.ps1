param([string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Stop'
$project = (Resolve-Path -LiteralPath $ProjectRoot).Path
$python = Join-Path $project 'venv\Scripts\python.exe'
$entry = Join-Path $project 'scripts\nightly_data_backup.py'
if (-not (Test-Path -LiteralPath $python -PathType Leaf) -or -not (Test-Path -LiteralPath $entry -PathType Leaf)) {
    throw 'Daily backup entrypoint missing.'
}
# Update only the existing owner-approved task; preserve its account/settings.
$task = Get-ScheduledTask -TaskName 'Astakos_Daily_Backup'
$action = New-ScheduledTaskAction -Execute $python -Argument ('"' + $entry + '"') -WorkingDirectory $project
$trigger = New-ScheduledTaskTrigger -Daily -At '00:00'
Set-ScheduledTask -TaskName $task.TaskName -TaskPath $task.TaskPath -Action $action -Trigger $trigger | Out-Null
