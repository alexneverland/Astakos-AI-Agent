# Memory maintenance

Chroma cleanup is a reviewed operation on specific record IDs. Age alone does
not make a memory disposable: dated family events, sessions, goals, documents
and photos retain their historical value.

Maintenance requires control of all writer launchers for the entire operation:
do not manually start another CLI, supervisor or container, and ensure no scheduled
launcher can start one. If this cannot be ensured, do not copy or mutate Chroma.
The cooperative pause covers its original participant snapshot; it is not a
global exclusion lock that prevents later launchers from starting writers.

Before inspecting Chroma, use the existing cooperative backup pause
(`services.daily_backup_runtime.cold_pause`) to drain registered writers. Capture
and hash-verify a private cold copy, calling the existing `assert_quiescent()`
immediately before and after capture. A newly detected writer aborts the capture;
do not accept a copy from a failed capture. Resume the supervisors before analysis and
inspect a disposable copy through Chroma's supported API; opening a client on
the original is not a read-only inspection.

Review document text and metadata together, including date, time scope,
provenance, confidence and linked assets. Keep separate observations from
different dates. Do not interpret an assistant status message as a user fact.
Do not classify content by a phrase list or automatically replace history with
LLM summaries. Record the selected IDs and reasons in a private local plan.

For an owner-authorized application, take another verified cold backup and call
`memory.maintenance.delete_reviewed_memories` while writers remain paused and
new launches remain excluded. Pass the reviewed collection name, complete
`id`/`document`/`metadata` records with a `reason` for each, and IDs that must be
retained; set `owner_approved=True` only for the owner's approved plan. This
operator-only API is not bound to conversational agents and never uses free-text
`delete_from_memory`, which can also remove structured profile facts.

The canonical operation requires an active native pause, rechecks each exact
record and keeper, persists a strict durable audit intent before deletion,
verifies all remaining records and writes a correlated completion receipt.
Unwritable or corrupt audit journals block deletion. If verification or the
completion receipt fails after deletion, retain the cold backup and audit intent
for recovery: an exception does not mean the deletion was rolled back. Close
the managed store before releasing the pause.

Recheck `assert_quiescent()` immediately before each read/delete and after
verification; abort on an unexpected writer rather than trying to pause or kill
it implicitly. Preserve the pre-apply backup if application cannot be verified.
Verify the exact remaining ID set
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
