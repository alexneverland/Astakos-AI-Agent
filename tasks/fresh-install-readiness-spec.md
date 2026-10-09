# Spec: fresh-install readiness

Owner authorization: 2026-10-09, make the documented capabilities ready for a
new installation. Extends the documentation/release assessment, preserving its
existing local edits and all unrelated observation tasks.

## Objective and assumptions

The normal routine database setup must provision the dated feedback schema for
new and existing installations. The existing canonical startup migration is the
authority; transport composition remains read-only. This is an additive schema
upgrade, not a baseline/confidence reset or reconstruction of old deliveries.
Optional credentials, Matrix homeservers and operator backup schedules still
require user configuration; do not silently provision those external services.
Office tooling availability must match the platform claims in the setup guide.

## Structure and style

Extend `memory/routine_feedback.py` and `memory/routine_db.py` through one canonical
schema initializer using the caller's SQLite transaction. Tests belong in
`tests/test_routine_feedback_installation.py`; retain existing runtime/importer
tests. Use typed functions/docstrings, e.g.
`def initialize_schema(connection: sqlite3.Connection) -> None:`. No new provider,
language parser, dependency or legacy history backfill is needed for this slice.

## Ordered slices and verification

1. Reproduce fresh setup missing the ledger with real temporary stores. Add
   preservation, repeat-startup, failure rollback and concurrent-startup cases.
2. Reuse the schema initializer in the existing serialized startup transaction;
   prove a fresh imported routine supports delivery and feedback across channels.
3. Audit remaining installation requirements, resolve executable provisioning
   where applicable, and update docs to the verified final behavior.

Focused command:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_routine_feedback_installation.py tests/test_routine_feedback_runtime.py tests/test_routine_db_connection.py tests/test_routine_json_importer.py tests/test_setup_wizard_routines.py -q -p no:cacheprovider
git diff --check
```

## Acceptance criteria

- Empty normal setup returns a complete compatible dated store without requiring
  a separate operator migration, including when no routine JSON was supplied.
- Existing routines, receipts, completions, baseline, pause, confidence and
  schedules survive repeat/additive migration; no fictional occurrence is inserted.
- Concurrent starters serialize the schema change; failure rolls it back and
  propagates rather than permitting partial activation or a silent legacy fallback.
- Fresh declared routines can receive a real injected transport receipt and
  persist feedback through the paired runtime, with all outbound calls mocked.
- Documentation reflects platform/setup limitations and no longer reports the
  resolved activation gap as open. Version/tag/image publication stays separate.

## Boundaries

Always use canonical memory APIs for production schema work and temporary fixtures
for tests. Never inspect/migrate/reset live owner databases, expose credentials,
contact providers, start transports or install host software during verification.
No automatic backup task creation or Matrix server deployment. No subagents.

## Packaging extension from the installation audit

The ignored Windows executable cannot serve fresh Docker/manual installs. Add
an explicit pinned native installer, one canonical binary resolver and build-time
provisioning in both Dockerfiles. Verify size/hash before atomic replacement;
never execute upstream installers or configure MCP. Preserve notices/licenses.

Release rsync must seed an absent context schema, update source registries/locales,
and protect runtime JSON/JSONL/locks, Matrix crypto/media and backup directories.
The image build context must exclude private runtime JSON while retaining tracked
source JSON. Verify the real script with synthetic old/new installations in a
network-isolated container; verify the built image and native executable.

## Wizard extension requested by owner

Expose all task-relevant configuration in its correct guided step, including
location pairs/radii, private backup destination, Office requirements, project
alias, Vertex project/region and existing optional GitHub/vacuum/LinkedIn/Spotify/Places tokens.
Preserve masked secrets and unrelated saved settings. Validate before writes and
exercise the actual HTML in a browser with every request intercepted locally.
Optional host/server provisioning and schedules remain explicit operator steps.

## Verified implementation checkpoint

320 focused routine/store/importer/Office tests and 80 Wizard/diagnostics/provider
cases passed. Native Linux AMD64 Office created/edited DOCX/XLSX/PPTX fixtures;
OpenXML validation passed. Source/release builds and offline API import passed. Real
rsync preservation failed against HEAD's overwritten context schema, then passed
with the new entrypoint. No live owner data, credentials or transports were used.

## PR #240 review follow-up

The owner authorized the verified findings on 2026-10-09. Wizard readiness and
adapter execution must use the same platform-specific size/SHA-256 validation;
an invalid local binary must not hide a valid Linux bundled fallback. Explicitly
empty optional non-secret guided fields remove saved values, including stale raw
form values. Omitted fields and masked secrets remain preserved. The offline
browser fixture must match the styling CDN by exact URL.

Four regression cases failed before repair; the nearby omitted-field case passed.
After repair, 110 focused Wizard/provider/Office cases passed with two existing
dependency deprecation warnings. All fixtures remained offline and temporary.
