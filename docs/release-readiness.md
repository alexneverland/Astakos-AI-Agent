# Release readiness: proposed v2.8.0

Assessment: 2026-10-09, merged `main` at
`4d40b1082f808a6a89a7baae32d7c93d185e5ef2` (PR #238), plus the local
fresh-install readiness changes. Latest published release: **v2.7.0**,
2026-09-11. `VERSION` remains `2.7.0`; no tag, release or image was published.

## Recommendation

Use **v2.8.0**, a minor release, for Matrix/Element, richer research/native file
workflows, behavioral conversation, dated/context-aware routines, goal continuity
and selective backups. The scope exceeds a patch release. No deliberate
incompatible API removal has been identified.

[CHANGELOG.md](../CHANGELOG.md) contains consolidated Unreleased notes.
[SETUP_GUIDE.md](../SETUP_GUIDE.md) distinguishes source and published images.

## Installation gaps resolved

- Canonical routine database setup provisions dated storage in its existing
  serialized transaction, including an empty installation without routine JSON.
  Existing schedules, pauses, confidence, receipts, feedback and baselines survive.
  Failures roll back, and concurrent startup serializes. Runtime composition stays
  read-only; no owner reset or historical delivery reconstruction was performed.
- The Wizard guides home/work coordinates and radii, private Drive backup folder,
  local project alias, native Office status/install instructions, Vertex project/
  region and optional GitHub/vacuum/LinkedIn/Spotify/Places access. Invalid structured settings
  fail before writes; saved masked secrets and unrelated settings are preserved.
- Both Dockerfiles provision checksum-pinned native Office CLI v1.0.154 and ICU
  on Debian Trixie. A bundled copy survives source Compose's `/app` bind mount.
  The explicit manual installer selects Windows/Linux/macOS x64 or ARM64 assets;
  platform selection is tested, not proof of execution on every architecture.
- Release refresh seeds context schema only when absent, updates source registries/
  locales and protects runtime JSON/JSONL, locks, databases, Matrix crypto/media
  and backups. The build context excludes private runtime data and host binaries.

## Verification and remaining release checks

- 320 focused offline routine/store/importer/Office tests passed; 80 Wizard,
  diagnostics and provider tests passed, including isolated browser form submission.
  Two existing dependency deprecation warnings occurred in the Wizard run. No
  provider/transport sends or live owner-data tests were performed.
- Real Linux AMD64 source and release image builds passed, with native Office v1.0.154.
  The source image native fallback also passed with an empty `/app` mount.
  Four network-isolated release container tests passed, covering fresh/existing rsync behavior, clean image
  inventory and real DOCX/XLSX/PPTX creation/editing with Greek text and OpenXML
  validation. API import passed using synthetic credentials and no network.
- The browser test substitutes the styling CDN: it verifies controls, validation
  and submitted payload, not production Tailwind appearance. Other UI regressions
  cover provider/transport switching. Native Office visual rendering was not tested.
- Run required CI and the publishing workflow's build/API smoke on the final
  release commit. ARM64 image execution and publication remain CI checks; Linux
  musl/Alpine and unverified platforms are not claimed as accepted deployments.
- Optional integrations require owner credentials; Matrix homeserver deployment,
  Element trust/recovery keys, local E5 installation and backup schedules are
  explicit setup steps. Saving a Drive folder does not install a scheduled job.
- Application-level data recovery and replacement-host/Element recovery remain
  separate observations. Backup capture/upload/extraction is not complete recovery.

## Publishing sequence after explicit authorization

1. Merge the scoped readiness/documentation changes through the PR process.
2. Update `VERSION`, date the v2.8.0 changelog section and update `SECURITY.md`
   support versions together; verify consistency and merge release preparation.
3. Create matching `v2.8.0`, publish release/setup assets and verify AMD64/ARM64
   images with versioned and `latest` tags.

The [publishing workflow](../.github/workflows/publish-ghcr.yml) validates VERSION
against a pushed `v*` tag; manual dispatch also publishes `latest`. Either can
update Watchtower users. Publication requires explicit owner authorization.
