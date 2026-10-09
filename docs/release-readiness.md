# Release verification: v2.8.0

Release checkpoint: 2026-10-09, including merged PR #240 at
`ca853c5` and the v2.8.0 release preparation. `VERSION` is `2.8.0`.
The owner authorized merging PR #240, deleting its branch and publishing the new
release. Check the [release page](https://github.com/alexneverland/Astakos-AI-Agent/releases/tag/v2.8.0)
and tag-triggered publishing workflow for artifact availability.

## Version scope

**v2.8.0** is a minor release for Matrix/Element, richer research/native file
workflows, behavioral conversation, dated/context-aware routines, goal continuity
and selective backups. The scope exceeds a patch release. No deliberate
incompatible API removal has been identified.

[CHANGELOG.md](../CHANGELOG.md) contains the dated v2.8.0 release notes.
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

## PR #240 review verification

PR #240 review follow-up: native Office selection and Wizard status now verify
the current platform's pinned size/SHA-256, including fallback from an invalid
local binary to the verified Linux bundle. Explicitly clearing optional
non-secret guided fields removes stale saved/raw values; omitted settings and
masked secrets remain preserved. The offline styling fixture matches an exact URL.
The regression run passed 110 focused Wizard/provider/Office tests (two existing
dependency warnings). A rebuilt Linux AMD64 release image passed all four isolated
container tests, including invalid-local fallback and real Office/OpenXML checks.
No release publication or live owner-data changes were performed.

## Security and upgrade recovery

The release updates `pypdf` from 6.16.1 to 6.19.0, the patched version covering
the eight open PDF parsing runtime/memory alerts checked on 2026-10-09. ChromaDB
server API advisories remain unpatched; supported deployments keep it embedded
and do not expose a Chroma HTTP server. This release is not a claim that all
upstream advisories have disappeared.

Preserve a pre-upgrade backup of the persistent data and separate credentials.
For an image rollback, stop Watchtower and pin the previous versioned image in
the deployment's Compose file before restarting the application. Do not remove
volumes or attempt to undo schema changes manually. Downgrading after new data
has been written is not verified; restoring the pre-upgrade data is a separate
operator recovery decision. See the backup guides for capture/recovery limits.

## Publishing sequence

PR #240 is merged; VERSION, the dated changelog and supported-version policy
are aligned to v2.8.0 in this release preparation.

1. Merge the verified release preparation, then create matching `v2.8.0` on that
   integration commit. The tag starts the existing image publishing workflow.
2. Verify the workflow's build/API smoke and published AMD64/ARM64 manifests,
   including matching versioned and `latest` image digests.
3. Publish the GitHub release with its setup/Compose assets and verification
   notes; confirm the release points to the same tag and commit.

The [publishing workflow](../.github/workflows/publish-ghcr.yml) validates VERSION
against a pushed `v*` tag; manual dispatch also publishes `latest`. Either can
update Watchtower users. Publication requires explicit owner authorization.
