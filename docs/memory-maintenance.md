# Memory maintenance

Chroma cleanup is a reviewed operation on specific record IDs. Age alone does
not make a memory disposable: dated family events, sessions, goals, documents
and photos retain their historical value.

Before inspecting Chroma, use the existing cooperative backup pause
(`services.daily_backup_runtime.cold_pause`) to drain registered writers. Capture
and hash-verify a private cold copy. Resume the supervisors before analysis and
inspect a disposable copy through Chroma's supported API; opening a client on
the original is not a read-only inspection.

Review document text and metadata together, including date, time scope,
provenance, confidence and linked assets. Keep separate observations from
different dates. Do not interpret an assistant status message as a user fact.
Do not classify content by a phrase list or automatically replace history with
LLM summaries. Record the selected IDs and reasons in a private local plan.

For an owner-authorized application, take another verified cold backup, recheck
each selected record and its retained counterpart, and use the existing memory
writer API while other writers remain paused. Verify the exact remaining ID set
and every retained document/metadata pair, record the deletion in the native
memory audit, close the managed store, and resume the existing supervisors.
Never publish the private report or backup in Git. A Chroma cleanup does not
implicitly authorize changes to the structured profile or conversation history.

## Retired entry points

`clean.py` and `scripts/chroma_memory_maintainer.py` have been removed. The former
could replace whole structured categories from LLM output or run unrelated
cleanup by default. The latter mixed history backfill with duplicate deletion
and ignored dated/provenance differences when grouping records. Do not use
copies of these old tools from earlier releases.

Ordinary new memories still go through the runtime memory sifter and canonical
memory manager. These runtime paths are not removed by this maintenance change.

## Audit log retention

The independent audit-log rotation command does not open databases, call an LLM
or change memories. Preview is the default:

```powershell
venv\Scripts\python.exe scripts\rotate_memory_audit.py --keep-days 60
```

Add `--apply` only when deletion of those old daily audit JSON files is intended.
Other JSON files, recent logs and linked files are preserved.
