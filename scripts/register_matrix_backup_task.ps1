param(
    [Parameter(Mandatory=$true)][string]$WorkDir,
    [Parameter(Mandatory=$true)][string]$RecipientFile,
    [Parameter(Mandatory=$true)][string]$AgeExecutable,
    [Parameter(Mandatory=$true)][string]$DriveFolder,
    [Parameter(Mandatory=$true)][string]$DeploymentDir,
    [string]$DailyAt = '03:00'
)
$ErrorActionPreference = 'Stop'
$taskName = 'Astakos_Matrix_Encrypted_Backup'
$repoDir = Split-Path -Parent $PSScriptRoot
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    throw 'Task already exists; inspect before updating it.'
}
$python = Join-Path $repoDir 'venv\Scripts\pythonw.exe'
$script = Join-Path $PSScriptRoot 'nightly_matrix_backup.py'
foreach ($path in @($python, $script, $WorkDir, $RecipientFile, $AgeExecutable, $DeploymentDir)) {
    if (-not (Test-Path -LiteralPath $path)) { throw 'Required task path is missing.' }
    if ($path.Contains('"')) { throw 'Unsupported quote in task path.' }
}
if ($DriveFolder -notmatch '^[A-Za-z0-9_-]+$') { throw 'Invalid Drive folder ID.' }
$arguments = '"' + $script + '" --work-dir "' + $WorkDir +
    '" --recipient-file "' + $RecipientFile + '" --age-executable "' + $AgeExecutable +
    '" --drive-folder ' + $DriveFolder + ' --synapse-dir "' + (Join-Path $DeploymentDir 'synapse') +
    '" --bot-store-dir "' + (Join-Path $repoDir 'matrix_store') +
    '" --compose-file "' + (Join-Path $DeploymentDir 'compose.yaml') +
    '" --deployment-environment-file "' + (Join-Path $DeploymentDir '.env') +
    '" --synapse-container neverland_matrix_synapse --postgres-container neverland_matrix_postgres'
$action = New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory $repoDir
$trigger = New-ScheduledTaskTrigger -Daily -At $DailyAt
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$settings.AllowHardTerminate = $false
$settings.StartWhenAvailable = $false
$task = New-ScheduledTask -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Private encrypted Matrix backup; graceful pause/restart; no plaintext upload.'
Register-ScheduledTask -TaskName $taskName -InputObject $task | Select-Object TaskName,State
