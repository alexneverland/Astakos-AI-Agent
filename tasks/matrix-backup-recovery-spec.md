# Spec: Private Matrix backup and recovery

Status: owner approved recipient encryption and installation. Key setup and a
harmless local round trip are complete. The owner confirmed vault storage and
copied the saved key back locally; that copy successfully decrypted the fixture.
First local live capture and an approved encrypted Drive upload with deployment
environment capture have passed. Opt-in canonical bot-runtime export is now
implemented and verified offline. Live recapture with those settings passed
vault-key decryption, manifest/hash validation and private Drive download checks.
Separate 03:00 Windows task and graceful coordinator are implemented. Its first
actual Scheduler invocation passed with exit 0, upload and verified channel/server
startup. Isolated PostgreSQL/Synapse restoration of the scheduled Drive artifact
passed, including token/room/sync and copied bot crypto loading. Temporary Docker
resources were removed; the owner removed plaintext rehearsal data and confirmed
local identity/fixture cleanup after vault verification. The timed 2026-10-04
03:00 invocation passed after the headless-handle repair: exit 0, durable uploaded
status and logged encrypted-channel recovery. Full Element/replacement-host
recovery verification remains open.

## Objective

Recover the self-hosted Matrix service after host loss, to the last verified
backup. Store only encrypted backup packages in Google Drive. Preserve the
existing Astakos daily backup and all unrelated pending work.

## Verified inventory (2026-10-02)

- Windows task `Astakos_Daily_Backup` runs at 22:00 and invokes
  `astakos_skills/daily_backup.py` from the Astakos root.
- That script recursively uploads the Astakos root, excludes some media/document
  extensions and credentials, and does not encrypt uploads. Per-file failures
  can be caught without a failing process exit. Task exit zero is not proof of
  a complete remote backup.
- Synapse: `neverland_matrix_synapse`, image
  `ghcr.io/element-hq/synapse:v1.161.0`; `/data` is bound to the private
  `C:\Neverland-Matrix\synapse` directory.
- PostgreSQL: `neverland_matrix_postgres`, image
  `postgres:17.11-alpine3.24`; data lives in a Docker volume, outside Astakos.
- Private compose location: `C:\Neverland-Matrix\compose.yaml`.
- The Synapse directory contains configuration, a signing-key file and media.
- The canonical runtime resolver confirmed Astakos uses the local `matrix_store`
  directory. Its stopped-store capture (including WAL/SHM) is verified; complete
  bot-runtime configuration/credential recovery still needs coverage.
- Initial inventory found no usable `age` executable on PATH. Subsequently,
  with owner approval, winget installed age 1.3.2 and verified the installer hash.
- Initial read-only inventory did not open credentials/database records/keys.
  Later owner-approved capture copied deployment secrets into encrypted staging
  without displaying values, and native dump tools copied the database.
- Encrypted remote upload/download integrity and isolated database/service
  recovery are verified. Owner Element recovery-key readiness remains unverified.

## Key-setup evidence (2026-10-02)

The recovery identity and public recipient were generated outside the project
and cloud-sync roots in the user's local AppData recovery directory. Directory
inheritance is disabled; permissions were verified to include only the current
user and SYSTEM. No key values were printed or committed. A non-sensitive copy
of this specification was encrypted and decrypted with age; SHA-256 equality
verified the round trip. The fixture is not a Matrix backup. The private key
remains local. The owner confirmed Google Password Manager storage and copied
the saved key into a second restricted local file. age successfully decrypted
the original non-sensitive ciphertext using that copy; SHA-256 equality with the
original decrypted fixture passed. Vault retrieval is owner-mediated evidence,
not direct agent access to Google Password Manager. No secret values were read
into chat. At this key-setup checkpoint, real capture was not yet verified;
subsequent live capture evidence is recorded below. Recovery remains unverified.

## Proposed key contract (requires owner agreement)

Use the established `age` recipient-encryption format, not custom cryptography.
Generate one recovery identity locally in a protected directory outside the
repository, Drive-sync paths and the existing recursive backup root. Never
display the identity in tool output, chat, command arguments or logs.

The scheduled backup receives only the public recipient. It cannot decrypt the
package and does not need a stored passphrase. The owner saves the secret
identity in a dedicated Google Password Manager entry (password field or note),
then verifies exact preservation using a harmless encrypt/decrypt fixture.
Google Password Manager supports manual entries and notes; this is not automatic
credential integration. Keep recovery access to the Google account available
after host loss. Do not remove the protected local recovery copy before the
owner confirms vault persistence and the harmless round trip succeeds.

This is a recovery key, not the Matrix login password or Element recovery key.
Element encrypted-history recovery remains a separate prerequisite.

## Backup scope and boundaries

Include a consistent PostgreSQL logical dump, relevant Synapse configuration and
server identity, media, deployment version inventory, and a consistent copy of
the bot's crypto state. Deployment secrets are allowed only inside the encrypted
package; scope their capture explicitly without printing or editing originals.
Do not claim that server signing keys decrypt message history.

Use the database container's matching `pg_dump`, not a live copy of PostgreSQL
data files. Inventory required roles/settings without exposing passwords.
Account for media changes while copying and bot-store writes. A brief coordinated
pause may be needed for the bot store; runtime stops require explicit approval.
Do not assume copying a live SQLite file alone preserves its WAL transactions.
Do not access Astakos databases with ad-hoc SQL or open Chroma.

Build plaintext staging in an access-restricted directory outside both source
roots and cloud sync. Never upload staging, secrets or recovery identities.
Archive and encrypt to a unique temporary output, validate completion, then
publish the final encrypted package atomically. On failure, retain the previous
known-good backup and return nonzero without printing sensitive subprocess output.
Reject symlink/reparse-point traversal and unexpected source/destination overlap.

Reuse the existing approved Workspace OAuth abstraction for an explicit upload
of the encrypted artifact; do not pass it through the old recursive uploader.
Confirm the private Drive destination before the first real upload. Avoid
overlapping runs with a durable lock. Use unique package/run IDs and a safe
resumable retry strategy. Do not delete remote backups in the initial version;
retention and storage budget require a separate owner decision.

## Project structure and code style

Candidate source: `services/matrix_backup.py` and a thin
`scripts/backup_matrix.py` entry point. Tests:
`tests/test_matrix_backup.py`; operator runbook under `docs/`.
Keep configuration outside `.env` and `config.py` changes unless separately
approved. Use typed functions, docstrings, explicit subprocess argument arrays,
injected transport/process boundaries and no provider calls at import time.
Example intended contract: `def run_backup(settings: BackupSettings) -> BackupResult`.

## Commands and verification

Package/encrypt/upload, guarded capture and nightly coordinator entry points exist.
Focused checks:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_matrix_backup.py tests/test_matrix_snapshot.py tests/test_matrix_nightly.py -q -p no:cacheprovider
.\venv\Scripts\python.exe -m py_compile services/matrix_backup.py scripts/backup_matrix.py
git diff --check
```

Official installation option, subject to approval and local availability:
`winget install --id FiloSottile.age --exact`.
Do not run this or generate keys during planning.

Offline tests use fixtures and mocked Docker/Drive boundaries, covering wrong
key, modified ciphertext, missing Docker/key/config, dump/encryption/upload
failure, concurrency, retry and no plaintext upload. No full-suite rerun.
Harmless local cryptographic round trip precedes any real data capture.
Restore rehearsal requires explicit authority for isolated containers/network/
volumes, no production host name/federation/outbound messaging, and no reuse of
production volumes. Remote package retrieval and successful isolated restoration
are required before marking recovery verified.

## Success criteria

### Approved bot-runtime slice

Capture is explicitly opt-in with `--include-bot-runtime`. Export only validated
Matrix runtime fields through `load_runtime_config`, plus the selected channel;
never copy the complete Astakos `.env`. Require the runtime crypto-store path
to match the stopped store being captured. Save `bot-runtime.json` only in the
private staging/package, include it in the hash manifest and remove staging on
completion. Recheck the resolved settings before publishing; failures hide raw
credential errors. Offline tests cover opt-out, field isolation, store mismatch,
changed settings, cleanup and CLI packaging. Live recapture/upload and restore
are separate verification checkpoints, not implied by passing fixtures.

- Only a complete encrypted package is uploaded; failed runs cannot report
  success or replace a known-good backup.
- Owner can recover the encryption identity from Google Password Manager and
  decrypt a fixture without the original host.
- Restore instructions reproduce the versioned service and address both bot
  crypto state and owner's Element key recovery.
- Final readiness is claimed only after an isolated restoration rehearsal.

## Ordered checkpoints

### Nightly execution slice (owner approved 03:00 local time)

Separate Windows task for the current interactive user, daily 03:00, limited
privileges. No password storage, old-task changes, daytime catch-up or parallel
instances. Lock the private work root; reject overlap with the old backup.
Discover exact local Matrix Python entrypoints; gracefully signal only the bot
process group and wait for bot/watchdog exit. Never kill on timeout. Capture and
encrypt, then restart only a previously running Matrix entrypoint in a hidden
console and verify startup before upload. Keep Web running. If Matrix was stopped
beforehand, leave it stopped. Always attempt recovery in finally; failures record
sanitized durable status and retain existing artifacts. Verify offline lifecycle
tests and one actual Task Scheduler invocation. Power loss cannot execute finally;
operator recovery may be needed. Isolated restore remains a separate checkpoint.

1. Approve recipient-key approach and dependency installation; establish vault
   preservation using non-sensitive fixture data.
2. Implement fixture-tested backup and explicit Drive upload; resolve snapshot
   consistency and sensitive-file capture scope before live execution.
3. Approve first real backup destination and runtime coordination; validate the
   remote artifact, then configure a separate nightly Windows task.
4. Approve and run isolated restore rehearsal; document evidence and limitations.

### First implementation slice

`services/matrix_backup.py`, `scripts/backup_matrix.py` and the operator runbook
implement packaging of an operator-prepared frozen snapshot, not capture of live
stores. The default is local encryption only. Drive upload is explicit and uses
the canonical OAuth helper, a durable preallocated file ID for retry, and remote
checksum/size/destination verification. Owned temporary plaintext is removed on
handled failure; crash remnants require scoped cleanup. No remote backups are
deleted. No live capture, credential read, Drive call or scheduled-task change
was performed during implementation. Do not mark the overall backup complete.
Verification: 26 focused tests passed, including real installed-age fixture
decryption, wrong-key/tamper rejection and mocked Drive ambiguous-response retry.
Python compilation, CLI help and diff whitespace checks passed. No full suite.

### Guarded collector slice

`services/matrix_snapshot.py` and CLI `--capture` now implement collection with
mocked-Docker regression coverage. Explicit pause approval and stopped Matrix
bot/watchdog are required. Actual configured PostgreSQL name, Docker alias/port
and Synapse bind mount are verified before pause. Native dumps and stopped-store
copies include media, signing/config files and bot WAL/SHM. Copy mutations fail;
restart is attempted on all post-stop failures, and container-running state is
checked before yielding a snapshot for encryption. Temporary captured plaintext
is cleaned on normal completion and consumer failure. At this collector checkpoint
automatic shutdown/scheduling were not implemented; the later nightly slice below
adds them separately. Container-running is not HTTP health.

Verification: 49 focused collector/packager tests, including capture-to-package
CLI integration, native Windows ACLs, `dbname` parsing and mocked encrypted upload.
First approved local live capture passed on 2026-10-02; the vault-retrieved
identity decrypted the artifact successfully and Synapse/bot were restarted.
The later owner-approved run included the deployment `.env` inside ciphertext
and uploaded it to a separately verified owner-only My Drive folder, not the
publicly link-readable existing Astakos parent. All decrypted-file hashes and
remote ciphertext download SHA-256 passed. Astakos's own `.env` was not captured.
No isolated PostgreSQL/Element restore or scheduled-task change occurred. Existing
nightly Astakos backup is untouched. See the operator runbook for artifact/checksum,
private Drive destination and health evidence; full recovery is not yet verified.

### Nightly coordinator and task verification

The owner approved 03:00 local time. The separate interactive/limited Windows task
uses resolved physical paths and no stored password. Graceful runtime coordination
is tested for capture/upload/restart failures, prior stopped state, duplicate lock,
process identity and no force kill. 72 focused tests passed. An actual invocation
through Task Scheduler completed with LastTaskResult 0 and durable uploaded status;
the encrypted channel started and Synapse was healthy/HTTP 200. The original
Astakos_Daily_Backup is unchanged. No Git commit, retention deletion or restore.

## Visible-terminal recovery amendment (owner approved 2026-10-02)

Keep an existing Matrix watchdog alive during the cold backup pause. Correlate
the request to its exact child and process ancestry; the live capture lock must
hold before the guard allows that specific idle watchdog. Unrelated launchers
and every live bot still block capture. The same parent restarts its child in
the existing terminal, with stdout/stderr also copied to private startup logs.
Boot and watchdog shutdown must clean up their current adopted child, not the
pre-backup process. A previously stopped channel stays stopped. No live backup,
credential changes or production process controls are part of offline testing.

Verification order: reproduce adopted-child Ctrl+C failure; test visible output
and private log tee; test correlated watchdog pause/restart and negative capture
guards; run focused pytest plus compilation/diff checks, not the full suite.

## Sources

- https://github.com/FiloSottile/age
- https://support.google.com/chrome/answer/95606?hl=en-GB
- https://www.postgresql.org/docs/17/app-pgdump.html
- https://docs.element.io/latest/element-server-suite-classic/administration/backup-and-restore/

Element Server Suite documentation supplies backup principles, not commands to
copy into this standalone Docker installation.
