# Daily data-only backup

## Owner-approved contract

Replace the recursive 22:00 code upload with a 00:00 cold data snapshot.
Pause all Astakos writers gracefully, snapshot locally, resume existing writers
in their original consoles, verify recovery, then upload one compressed package.
Only after verified upload may older daily backups in the same configured Drive
parent be trashed. The separate 03:00 encrypted Matrix backup is unchanged.

## Scope and boundaries

Include canonical SQLite databases and their cold WAL sidecars, the complete
current Chroma directory, explicit runtime-state JSON files, personal persona,
custom intents and indexed photo/document binaries. Exclude Git/code/tests,
vendor, logs, TEMP, historical backups, unindexed outputs, credentials and .env.
Record Git revision, inventory, checksums and indexed-file mappings in a manifest.
Reject missing indexed assets, unsafe paths/links, concurrent runs, changes during
capture and unconfirmed writer shutdown. Never force-kill to manufacture success.
Failing capture/upload/recovery preserves the previous remote backup. Retention
uses scoped parent, exact daily-backup identity and pagination, never broad Drive
name matching. Partial uploads are not successful backups.

## Implementation order

1. Offline selection and cold package verification (services + fixture tests).
2. Single verified upload and scoped trash retention (mock Drive tests).
3. Correlated writer pause/resume, visible-console continuity and schedule switch.
4. Owner-approved live capture/upload and restore verification.

## Verification

Python type hints/docstrings; pytest fixtures and mocked transport/process edges.
Run focused tests with `venv\Scripts\python.exe -m pytest
tests/test_daily_data_backup.py -q -p no:cacheprovider`; `git diff --check`.
Never inspect original SQLite with raw SQL or open original Chroma for testing.
No new dependency, config/secret change or Matrix backup change. Git publication
is a separate owner-authorized step after verification; no runtime data is committed.
