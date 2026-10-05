# Last30Days Vendor Provenance

- Source: https://github.com/mvanhorn/last30days-skill
- Release: `v3.26.0`
- Commit: `5103ba478b380552207a3754b74c7655d64208cd`
- Synced: 2026-10-05

## Scope

The vendored distribution contains upstream `LICENSE` and the complete
`skills/last30days/` release subtree. Existing additional media assets are
preserved. Upstream repository development policy, MCP server, plugin
installations, workflows and root configuration are not installed in Astakos.
No credentials, browser-cookie consent or runtime configuration are changed.

The prior distribution matched v3.11.1 apart from five additional media assets.
The obsolete Reddit RSS module is removed as in upstream; Reddit discovery
now uses the public site search path. Upstream's MIT license and the nested
bird-search attribution remain intact.

## Astakos integration

`astakos_skills/research_last30days.py` continues to request `--emit md` and
uses the existing 120-second timeout and localized error handling. The child
uses the running Python interpreter when it is >=3.12 (the upstream minimum,
also required by v3.11.1). For a Python 3.11 application it probes PATH Python
executables and the Windows `py -3` launcher, accepting only a verified >=3.12
version. No interpreter is installed and the application runtime is unchanged.

Upstream v3.26.0 permits paid ScrapeCreators Reddit backfill when fewer than
five free items are found. Astakos keeps the former empty-only behavior by
defaulting `LAST30DAYS_REDDIT_SC_MIN_ITEMS` to `0` in the child process only;
an explicit process environment value is preserved. No `.env` file is edited.
Other providers and modes retain upstream defaults and existing configuration.

## Verification boundary

Local contract tests use fixture retrieval, temporary working directories,
mocked configuration/secret resolution and a fail-closed socket boundary.
No paid/live research or browser-cookie extraction is performed. Production
provider availability and research quality still require a user-approved live
request; fixture tests do not establish them.

Verified results on 2026-10-05:

- Six Astakos contract tests passed, including the actual fixture-mode CLI.
- 199 focused upstream cases passed across runs (Reddit search, output
  boundaries, cookies, HTTP, redirect authorization and permission preflight).
  Two localhost redirect cases initially encountered the outbound guard;
  the six-case redirect file then passed with loopback-only access allowed.
- All 136 imported release files match the pinned upstream bytes. Five
  pre-existing additional media assets remain unchanged.

## Local review patches

Following PR #218 review, the CLI's `public_device_auth_result`, its
device-auth JSON output call and `lib/setup_wizard.py` profile error handling
are local security patches to the pinned release.
The original 136-file byte comparison describes the import before this patch;
all other imported files remain unmodified apart from these two files.

Device-auth output uses a bounded public schema instead of serializing the
provider result. It omits API keys, private device handles, unknown fields and
free-form provider message/error bodies. Public authorization codes, status,
HTTP status and persistence outcome remain available. Key persistence still
uses the private result and is tested without writing real configuration.

The remaining CodeQL alert #72 on commit `6c1a1fa` traces
`fetch_api_key()`'s aggregate result through its `http_status` field to the
public JSON. This particular flow is a false positive: the output accepts only
an exact `int` in the HTTP status range 100..599, not provider strings, objects
or booleans. Focused regression cases verify this boundary. No CodeQL rule is
suppressed or disabled; the original raw-result output remains removed.

The later Codex review identified a separate stderr leak at the profile HTTP
boundary. That path now reports only numeric HTTP status or a fixed network
failure message, never response bodies, server reasons or exception text.
Real CLI/device-auth/profile regression tests mock only external I/O and cover
401, 503 retry exhaustion and network failure. All CLI subprocess tests share
the production compatible-interpreter resolver, including a simulated Python
3.11 host launching real compatible Python. The focused suite passes 25 cases.
