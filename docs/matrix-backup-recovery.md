# Matrix encrypted backup: operator runbook

## Current readiness

Packaging, encryption, explicit Drive upload and the guarded snapshot collector
are implemented and tested with synthetic snapshots and mocked Docker/providers.
The deployment environment is now included in a verified private Drive artifact.
Canonical bot settings and automated bot/watchdog coordination are implemented.
The separate Windows nightly task is registered and its first Task Scheduler
invocation completed successfully. An isolated database/service restore passed
on 2026-10-02 (details and remaining limitations below). The existing Astakos
backup task is unchanged.

### First local live capture (2026-10-02)

The owner approved a local-only run. Matrix bot/watchdog were gracefully stopped;
Synapse was paused for native PostgreSQL dumps and stopped-store/media copying,
then restarted. The final encrypted artifact was created at 13:05 UTC:
`matrix-backup-20261002T130509Z-eec97e37294044fda3f1a75b2bbc4bff.age`
(5,554,216 bytes, SHA-256
`f663d663adcc31b917d0e8c8615c259a552a6b48ed9a5f51c8b082c96b7f2983`).
It remains in the private local work root, not Drive or Git.

Decryption with the previously owner-retrieved vault identity passed, with output
discarded rather than extracted. Owned plaintext capture/archive staging was
absent after the run. Synapse was healthy and its client versions endpoint
returned HTTP 200; the restarted bot logged encrypted-channel startup without a
startup failure. That historical rehearsal restarted the watchdog hidden with
private logs; the owner later stopped it and reopened the visible launcher.
Current nightly behavior keeps the existing parent/terminal (see below).
The owner subsequently confirmed normal Element replies.

No `.env` was copied or modified. Deployment environment capture must be explicitly
approved before claiming full host-loss recovery. No Drive upload, scheduled-task
change or isolated database/service restoration occurred. Decryption is not proof
that a PostgreSQL restore or Element history recovery succeeds.

Live preflight exposed three fixture gaps, now regression-covered: PostgreSQL's
`dbname` configuration key, native Windows staging ACLs with extra explicit
grants, and shell restart instructions incorrectly counted as running bots.
The focused collector/packager suite passed 49 tests; no full suite was run.

### First approved Drive upload (2026-10-02)

The owner approved capturing `C:\Neverland-Matrix\.env` solely inside the encrypted
package and uploading that package. A new consistent snapshot includes it as
`deployment.env`; the original was not modified and its values were never printed.
Decryption and all archived-file hashes were verified in memory without extraction;
the environment-file hash matched the approved source. Astakos's own `.env` was
not copied: recovery of Matrix bot runtime settings/access credentials must still
be covered before declaring full automated host-loss recovery.

The existing configured Astakos Drive parent had an `anyone/reader` permission.
Its sharing was not changed. Instead, the separate
[Astakos Matrix Encrypted Backups folder](https://drive.google.com/drive/folders/1DShT2_g5aeMpAkRQ36fGZEOBGG2Psbrz)
was created directly under My Drive; folder and uploaded file permissions were
verified as owner-only.

Uploaded artifact:
`matrix-backup-20261002T131557Z-8736be26f9b84aff85bbcfeee7aef8ba.age`
(5,582,705 bytes; SHA-256
`d33e0729c59af66bdff97f593204a56857ee4b03f9c7f33e9b4ecefc0202a05b`).
Remote size, MD5, destination and stored SHA-256 metadata passed; a real download
of ciphertext into memory also matched SHA-256. No plaintext or recovery identity
was uploaded. Earlier local backups remain intact; no retention deletion occurred.

Synapse returned healthy/HTTP 200 and the bot logged encrypted-channel startup.
Owned plaintext staging was absent. No new nightly task, Git commit/push or
isolated PostgreSQL/service restoration was performed.

Do not point this script at an active PostgreSQL data directory, live Synapse
installation or live bot crypto store in prepared-snapshot mode. The completion marker is an
operator attestation, not automatic evidence that writers have stopped.

## Keys

The owner keeps the recovery identity in Google Password Manager. Key setup and
an owner-mediated retrieval/decryption check passed on 2026-10-02. The backup
process uses only the public recipient file. Never put the secret identity in a
snapshot, the repository, Drive, shell arguments or logs. Both local recovery
copies were removed by the owner after successful vault retrieval and the live
restore rehearsal. Only the public recipient remains locally for scheduled
encryption. Retrieve the secret identity from the vault for future restoration;
never upload it with a backup.

Element recovery keys are separate. Confirm owner's secure key backup/recovery
before claiming old encrypted conversations will survive host loss.

## Prepared snapshot contract

An approved collector must produce a frozen/private snapshot with:

```text
snapshot/
  snapshot.json
  postgres.dump                 # PostgreSQL custom-format dump (PGDMP)
  postgres-roles.sql             # required roles/settings; encrypted contents only
  compose.yaml
  synapse/
    homeserver.yaml
    server.signing.key           # actual relative name declared in snapshot.json
    media_store/
  bot-store/
    matrix_store.db
    ...                         # complete bot state, including associated files
```

Include required deployment environment/configuration in the frozen snapshot
only after scoped sensitive-file capture approval. Full live crypto-store
capture and PostgreSQL/media consistency must be solved by the collector. Do not
copy a live SQLite file without its consistency boundary. Store versioned image
identifiers and a real capture timestamp; do not fabricate them.

Example marker shape (illustrative values only):

```json
{
  "format_version": 1,
  "consistent": true,
  "captured_at": "2026-10-02T10:00:00+00:00",
  "signing_key": "synapse/server.signing.key",
  "images": {"synapse": "pinned-image", "postgres": "pinned-image"}
}
```

The packager checks required files, rejects links/junctions and recovery-key
file prefixes, hashes source files, verifies the tar's actual contents against
its manifest, and rejects detected changes. These checks do not replace a
consistent capture or prove a database dump is fully restorable.

## Explicit execution (do not run against production yet)

After approving the collector and first live capture, substitute real private
paths. Use a work directory outside the source, repository and cloud-sync roots.
The script applies restrictive staging permissions before writing plaintext.

```powershell
.\venv\Scripts\python.exe scripts\backup_matrix.py --snapshot-dir C:\PrivateSnapshot --work-dir C:\PrivateBackupWork --recipient-file C:\PrivateKeys\recipient.txt --age-executable C:\Tools\age.exe
```

Default mode creates only a local `matrix-backup-<time>-<uuid>.age` artifact. It
does not authenticate Google, upload, stop containers or schedule tasks. The
plaintext tar lives only in an owned staging directory, removed on completion
or handled failure. A process crash can leave staging; cleanup after a crash
needs a scoped operator decision and must never delete an active run's files.
Filesystem deletion is not guaranteed secure erasure on SSDs.

### Guarded capture mode

`--capture` requires explicit source paths, both container names, the public
recipient, private work root and `--allow-server-pause`. It refuses to run while
any Matrix bot/watchdog entry point is running, except the nightly coordinator's
exact watchdog PIDs after that parent acknowledges its child has exited, while
the coordinator's capture lock is held. A live bot always blocks capture.
The standalone capture CLI has no such lease and still requires all launchers
stopped for the entire capture.
This low-level capture CLI never terminates the bot. Nightly coordination uses
the separate coordinator described below; no forced termination is implemented.

Before stopping anything, the collector checks the Synapse bind mount, actual
configured database name, shared Docker-network PostgreSQL alias and port, and
supported signing-key/media paths. Unsupported layouts fail rather than silently
omit data. It pauses only Synapse, uses native `pg_dump`/`pg_dumpall` in PostgreSQL,
copies the stopped server tree and complete bot store (including WAL/SHM), and
rejects observed source changes. Deployment environment capture is optional and
requires an explicit `--deployment-environment-file`; no environment file is
automatically discovered.

It attempts to restart Synapse after every stop attempt, including failed dumps
or copying, and verifies the container is running before encryption or upload.
Running is **not** proof of HTTP readiness; first live execution must also check
server/client health. Temporary captured plaintext is removed when packaging
returns or raises. The private capture and package work directories are siblings.

Illustrative command only, not authorization to run against production:

```powershell
.\venv\Scripts\python.exe scripts\backup_matrix.py --capture --allow-server-pause --synapse-dir C:\PrivateDeployment\synapse --bot-store-dir C:\PrivateBotStore --compose-file C:\PrivateDeployment\compose.yaml --synapse-container APPROVED_SYNAPSE --postgres-container APPROVED_POSTGRES --work-dir C:\PrivateBackupWork --recipient-file C:\PrivateKeys\recipient.txt --age-executable C:\Tools\age.exe
```

Add `--upload --drive-folder <approved-folder-id>` for an explicit upload. Do not
use the old recursive daily uploader: it has different exclusions and may upload
plaintext. The new path verifies remote size, MD5, destination and stored SHA-256
metadata. SHA-256 is rechecked locally after the upload. Only remote verification
produces an `uploaded` status and success exit code. No remote retention/deletion
policy is activated.

If an upload response is ambiguous, preserve the encrypted artifact and its
`.age.upload-id` and `.age.sha256` receipts together. The original encryption
checksum is persisted before any upload. Retry rejects missing/invalid receipts
or changed ciphertext before provider access; it never invents a new trusted hash.
Legacy packages without a checksum receipt cannot use this automatic retry path;
retain them for recovery using previously recorded, verified checksums.
Retry the **same** artifact, not a new run:

```powershell
.\venv\Scripts\python.exe scripts\backup_matrix.py --retry-artifact C:\PrivateBackupWork\matrix-backup-EXAMPLE.age --upload --drive-folder APPROVED_FOLDER_ID
```

The preallocated Drive ID and upload lock prevent a second copy after an
ambiguous create. Conflicting or corrupted remote metadata fails safely rather
than overwriting it. OAuth is resolved only through the canonical Astakos
Workspace helper after explicit upload opt-in. Do not print provider exceptions.

## Restore rehearsal checkpoint

### Optional bot-runtime recovery settings

Add `--include-bot-runtime` to an approved capture to include `bot-runtime.json`.
This contains only the canonical validated Matrix homeserver, bot token/account,
owner/device allowlist, room, store/media paths and selected-channel setting.
It does not copy Astakos's complete `.env` or unrelated provider credentials.
The selected channel must be Matrix and the resolved store must match the cold
store being copied. Resolved settings and the source environment-file fingerprint
are checked again during capture. The JSON stays in restricted staging, is hashed
in the encrypted archive and is removed with staging on completion/failure.

On another host, review the exported settings and adjust local paths through the
normal setup process; do not blindly replace the whole `.env`. Restore the matching
crypto store with the service account. A revoked token requires normal reauthentication;
this backup does not verify/trust new devices or replace Element's recovery key.
This slice passed 55 focused fixture tests, including CLI packaging and upload
boundaries. The first two real artifacts predate this option; use the verified
recapture below when bot-runtime recovery is required. Isolated restore is pending.

### Verified recapture with bot settings (2026-10-02 13:35 UTC)

- Artifact: `matrix-backup-20261002T133525Z-e17d990ab62e45f58dd38269c6427769.age`.
- Size: 5,596,288 bytes; SHA-256:
  `ed9f9356ab2d9c04ad6c745c59ae31638da5618e8aabc47c93ab1c62174069e1`.
- [Private Drive artifact](https://drive.google.com/file/d/1achw-9Zl2NxbJTVCKFtcGId8S68l_fnG/view?usp=drivesdk).
  Owner-only permissions and the independent private parent were rechecked.
- Remote download SHA-256 matched; the vault-retrieved identity decrypted the
  archive in a stream without plaintext extraction. Every file matched the
  internal manifest. Bot-runtime settings matched the canonical resolver;
  deployment environment matched its source, with no secret values displayed.
- Owned capture/package plaintext staging was removed. No old backups deleted.
- Synapse healthy and client versions endpoint HTTP 200. Graceful bot shutdown
  completed; the first restart dispatch failed because the coordinator command
  escaped its Windows path incorrectly. The corrected direct PowerShell launch
  succeeded and watchdog/bot processes were present. Buffered startup logs did
  not yet prove chat delivery; owner live reply confirmation remains pending.
- No `.env` edit, scheduled-task registration, Git commit or isolated restore.

Do not restore into production. First approve isolated volumes/containers and
network restrictions. Retrieve the encrypted artifact, verify it against the
recorded checksum, and decrypt using a locally restored recovery identity. Use
age's output option, not shell redirection of binary archives.

Validate archive names/types before extraction into an empty isolated directory;
never blindly extract a downloaded tar. Verify every file against the internal
manifest, validate the PostgreSQL dump with the matching restore tool, and restore
roles/database before starting the pinned service images. Prevent federation,
notifications and bot outbound sends. Restore required server configuration,
identity/media and the consistent bot crypto state separately. Account for client
E2EE state after restoring an older database snapshot; server rollback is not
guaranteed transparent to existing devices.

A successful upload is **not** proof of recovery. Record an actual isolated
rehearsal and its limitations before marking backup/recovery complete.

## Nightly Windows operation

`boot.py --server` starts its Matrix child in a dedicated Windows signal group.
For a backup, the coordinator publishes a local request correlated to that exact
parent/child PID and holds a capture-pause lock. The boot supervisor keeps Web
running during the pause, then restarts and owns the replacement Matrix child.
Ctrl+C cleanup runs in the scope that owns the current replacement process.
For Windows Matrix children, boot signals their dedicated group with CTRL_BREAK
and allows up to 120 seconds for archival shutdown. Before signaling, it retains
Windows handles for the launcher and its current descendants and waits for all
of them, even if the venv shim exits first. Creation times reject stale ancestry;
retained handles prevent PID reuse from redirecting cleanup. If explicit launcher
shutdown cannot complete gracefully, it stops only those retained identities.
This fallback is not used by the
nightly capture coordinator, which continues to refuse force-kill on timeout.
With launcher choice 1 (`run_external.py` / `run_matrix.py`), the watchdog stays
alive in its original terminal, acknowledges the stopped child, waits for capture
to finish, then restarts under the same parent and console. Recovery stdout/stderr
are copied both to that visible terminal and private startup-evidence logs.
The coordinator verifies fresh startup logs before upload and does not start a
second detached bot. Unrelated exits still fail through normal supervision.
Requests/locks are gitignored; requests contain no credentials and are removed
after recovery. A coordinator crash releases its OS lock; the correlated boot
parent can resume rather than remaining paused by a stale lock file.
After updating this code, previously running boot/watchdog parents must be normally
restarted before relying on this contract (a source reload replaces only the bot,
not the watchdog's own loaded code). No live parent restart was performed as part
of the correction tests. Direct bot launches without a supported owning parent are
rejected before downtime; they cannot be safely restored into an existing terminal.

Task: `Astakos_Matrix_Encrypted_Backup`, daily **03:00 local Windows time**.
Runs as `PC`, interactive logon, limited privileges, using the venv's `pythonw.exe`.
The machine must be on, the user logged in (a locked desktop is fine), and Docker
and network available. It does not wake the machine or catch up missed runs in
daytime. Concurrent task instances are ignored, and a separate coordinator lock
guards manual overlap. No Windows password or secret recovery identity is stored
in task arguments. Only the public recipient is used by encryption.

`scripts/nightly_matrix_backup.py` checks that the old Astakos backup is not running
and that the Drive folder is owner-only before downtime. It gracefully signals
the discovered local venv bot group, waits for the bot to exit and its watchdog to
acknowledge the capture pause, reuses the cold collector/encrypter, then releases
the parent to restart in the same terminal. No detached hidden recovery fallback
is used. Startup must be observed before upload; Web stays running. A previously
stopped Matrix channel is left stopped. No force kill on timeout. Existing backups
are retained; no retention deletion or automatic retry of old failed uploads.

Task hard termination is disabled and execution-time limit is zero so Scheduler
does not interrupt recovery in `finally`. Power loss, manual process kill or a
fatal interpreter crash can still bypass cleanup: inspect Synapse/bot and owned
private staging before the next attempt. A hung task requires operator diagnosis;
the next instance is ignored. Failures record sanitized status and exit nonzero.
Use the established same-artifact retry CLI for upload failures.

Local paths are **physical resolved paths**, not Codex's virtualized AppData aliases:

- Work root: `C:\Users\PC\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\AstakosMatrixBackupWork`.
- Status: `last-run.json` under that root. Contains timestamps, safe failure code,
  artifact/hash and confirmed Drive ID. It does not contain secret settings.
- Private runtime logs: `runtime/nightly-matrix.out.log` and `.err.log`.
- Public-recipient file lives in the sibling `AstakosBackupRecovery` directory.
  Recovery identity is not needed or passed to the task.

`scripts/register_matrix_backup_task.ps1` is the reproducible registration helper.
It refuses to overwrite an existing task and requires explicit work/key/tool/Drive/
deployment paths. The deployed age executable path is version-specific; recheck
it after reinstall/upgrade. Change this new task only, not `Astakos_Daily_Backup`.
Rollback is disabling `Astakos_Matrix_Encrypted_Backup`; this preserves artifacts
and all existing backup settings.

### First scheduled-entrypoint verification

On 2026-10-02 at 16:46 local, `Start-ScheduledTask` ran the actual registered
limited-privilege action outside Codex. Task returned to Ready with LastTaskResult
`0`; durable status was `uploaded`, finishing at 13:47:25 UTC. Runtime logs confirmed
encrypted Element-channel startup without startup failure; Synapse healthy and
client versions endpoint HTTP 200. Next run: 2026-10-03 03:00 local.

Artifact: `matrix-backup-20261002T134708Z-91b3c9396a8841e5b8f819eb1628b68e.age`,
5,600,978 bytes; SHA-256
`8ed2937f6304923be2157a98974af11e19cbf160aa6d69b06c6054c2febe938f`.
Confirmed Drive ID: `12WMFBWexr7Upv_ulrmlnZRlX52vk8r6E`.
Uploader verified remote size/MD5/parent/stored SHA and local post-upload hash.
This scheduled artifact passed the isolated database/service restore below.
72 focused offline backup/snapshot/coordinator tests passed; no full suite.

### Isolated restore rehearsal (2026-10-02)

The scheduled artifact above was downloaded from its owner-only Drive folder.
Ciphertext SHA-256 matched; the owner-retrieved vault identity decrypted it, and
every archive member matched the internal size/hash manifest before safe
extraction into a restricted, new rehearsal directory.

Native PostgreSQL 17 tools restored the roles and custom-format database dump
with error-stop enabled into a new volume. Synapse v1.161.0 started from the
copied configuration, signing identity and media directory. Both containers used
only a new internal Docker network, with no published ports. Federation, pushers,
registration and statistics reporting were disabled by a separate rehearsal
overlay; production configuration and services were not changed.

Read-only localhost API checks inside the isolated Synapse verified versions,
the restored bot token/account, the expected joined room and successful sync.
The copied nio SQLite crypto account and inbound session store loaded using the
same default pickle configuration as the real client. No bot was started and no
messages, reactions, notifications or federation events were sent.

The packager-input inventory cannot be used after extraction: it deliberately
rejects the generated `backup-manifest.json`. The restore instead verified each
extracted file against that manifest. This is not an archive integrity failure.

All labeled rehearsal containers, volume and network were removed after checking
their ownership. Production Synapse remained healthy, with client HTTP 200.
Automatic deletion of the restricted plaintext directory was blocked by the
execution policy. The owner removed that exact rehearsal directory; its absence
was subsequently verified. The owner also confirmed removal of both local secret
identity copies and non-sensitive fixture artifacts. Encrypted packages and the
public recipient remain; the vault is the retained recovery-identity location.

Limitations: this is a same-host isolated restore, not a replacement-host or
owner Element recovery-key test. Successful sync and crypto loading do not prove
decryption of every old attachment/message or transparent client recovery after
a server rollback. The next timed 03:00 run after the headless-handle repair
remains to be observed.

### Headless Scheduler diagnostics

The status file records `stage`, `failed_stage` and bounded `error_code` fields;
`recovery_error_code` keeps a separate recovery failure without erasing the
original failure. Arbitrary exception messages and secrets are not recorded.
Non-interactive PowerShell, Docker, ACL and encryption subprocesses explicitly
use DEVNULL stdin so an invalid console handle cannot break checks after handoff.

The 2026-10-03 03:00 run failed. A native pythonw fixture reproduced WinError 6
for inherited invalid stdin. The actual Scheduler retry with the repair completed
at 08:49:57 local (about 63 seconds), LastTaskResult=0, with verified encrypted
Drive delivery, healthy Synapse and Matrix resumed under the original watchdog.
This is manual Scheduler evidence, not proof of the next timed invocation.

### Verification commands

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_matrix_backup.py tests/test_matrix_snapshot.py tests/test_matrix_nightly.py -q -p no:cacheprovider
.\venv\Scripts\python.exe -m py_compile services/matrix_backup.py services/matrix_snapshot.py scripts/backup_matrix.py scripts/nightly_matrix_backup.py
git diff --check
```

Provider interactions are mocked. The optional installed-age test generates
disposable keys and exercises only synthetic local fixtures, wrong keys and
tampered ciphertext. It never reads owner keys or real databases.
