# Daily Astakos data backup

This describes the Windows operator workflow on current `main`. It is separate
from Docker volume persistence and from the [encrypted Matrix backup](matrix-backup-recovery.md).
Neither scheduled job is installed automatically by the Setup Wizard or release compose file.

## What it saves

The midnight job creates a selective cold ZIP with an integrity manifest:

- Explicitly selected SQLite databases and their existing sidecars.
- The Chroma memory directory.
- Selected settings, context, working memory, profile/persona and pending state.
- Meal history and saved recipes.
- Photos and documents referenced by the canonical media indexes.

It excludes application code, the virtual environment, vendor files, logs,
temporary files, previous backups, unindexed generated outputs and credentials,
including `.env`. This archive is **not encrypted by this job**; keep its Drive
destination private. Preserve credentials and custom assets outside the selected
inventory separately through a secure owner-controlled backup.

The collector rejects unsafe paths and missing indexed assets rather than
silently calling an incomplete package a success. Do not delete original indexed
files to work around a failed backup.

## How it runs

`scripts/nightly_data_backup.py` coordinates a graceful pause of the supported
local writers, verifies quiescence and packages the data. Writers resume before
Drive upload and retention. Only a verified upload permits scoped removal of
older daily backups in the same destination. Failed capture, recovery or upload
must not remove the previous remote backup.

The existing owner deployment runs `Astakos_Daily_Backup` at **00:00 local time**;
the separate encrypted Matrix task runs at **03:00**. These are registered Windows
tasks, not portable defaults for every installation. The registration helper
`scripts/register_daily_backup_task.ps1` updates an existing approved task and
preserves its account/settings; it does not create a task on a clean machine.
Scheduling, runtime changes and live execution require explicit owner scope.

## Inspect a configured installation

The selected runtime-state inventory also includes `known_places.json`, the
owner's custom named GPS locations. Configured home/work geometry remains part
of its existing configuration; credentials and transient GPS queues keep their
separate recovery requirements.


These read-only PowerShell commands show the registered task and last result:

```powershell
Get-ScheduledTask -TaskName Astakos_Daily_Backup | Select-Object TaskName, State, Actions, Triggers
Get-ScheduledTaskInfo -TaskName Astakos_Daily_Backup | Select-Object LastRunTime, LastTaskResult, NextRunTime
Get-Content -LiteralPath .daily-backup-status.json
```

Run from the configured project root. A missing task/status file means there is
no evidence from that source. Require both Scheduler success and job
`status=complete`, then check the recorded artifact and resumed application.
An uploaded filename or a successful process exit alone is insufficient recovery evidence.

## Evidence and recovery limits

The owner deployment has recorded cold capture, pause/resume, private Drive upload,
scoped retention and isolated extraction with matching hashes. The automatic
2026-10-03 midnight invocation completed successfully. These dated observations
are recorded in [tasks/todo.md](../tasks/todo.md); they are not a fresh check of
today's Scheduler or Drive.

Application-level recovery on an isolated installation remains unverified.
Restore rehearsals must use separate storage and the matching application version,
with outbound transports/providers disabled. Do not restore over live data or
open an original Chroma store for a rehearsal. Matrix server data, bot crypto
state, Element recovery keys and credentials have separate recovery requirements.
