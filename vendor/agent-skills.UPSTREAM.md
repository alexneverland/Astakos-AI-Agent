# Agent Skills Vendor Provenance

- Source: https://github.com/addyosmani/agent-skills
- Release: `0.6.12`
- Commit: `a06bc63b3f8b829c14b0bbf53d99fefc39d58092`
- Synced: 2026-10-05

The `vendor/agent-skills/` directory was synchronized from that release. These
Astakos-owned additions are retained and validated against the current schema:

- `skills/astakos-skill-authoring/SKILL.md`
- `evals/cases/astakos-skill-authoring.json`

Astakos-specific workflow policy belongs in the repository-root `AGENTS.md`,
not in the upstream repository's own `AGENTS.md`.

`scripts/validate-versions.js` reads the release above when run from this
vendored layout, independently of the caller's working directory. Its test
uses the same rule. In a standalone upstream checkout both validate against
the root `plugin.json` version, following upstream 0.6.12.

The earlier Astakos session-start test adaptation is now covered by upstream's
standard hook-envelope checks. The whitespace-only adaptations in
`docs/commandcode-setup.md` and `docs/cursor-setup.md` remain unchanged.
The duplicate `hooks/hooks.json` was removed by upstream; no Astakos runtime
or repository-root workflow settings were changed.

`scripts/validate-reference-links.js` also strips nested inline markup to a
fixed point before deriving plain heading anchors. A focused regression in
its test file covers nested markup, ordinary tags, and an absent anchor. This
local adaptation addresses CodeQL alert #71 without disabling security checks.

## Local verification (2026-10-05)

- All 26 skills pass schema/lint validation; versions, reference links,
  command parity, and artifact paths pass their validators.
- Offline skill evals: 146 checks passed; trigger rank-1 rate 91/92 (99%).
- Focused upstream Node regression tests: 173 passed, 0 failed.
- Session-start JSON envelope test passed; simplify-ignore tests: 21 passed.
- Full simplify-ignore lifecycle and sdd-cache tests requiring `jq` were
  skipped because it is not installed; those hooks no-op without `jq`.
- Astakos-owned skill and eval hashes are unchanged. Release contents match
  upstream apart from the documented local adaptations. `git diff --check`
  passed. No live provider/plugin-install tests or Astakos runtime tests ran.
