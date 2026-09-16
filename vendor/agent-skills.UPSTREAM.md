# Agent Skills Vendor Provenance

- Source: https://github.com/addyosmani/agent-skills
- Release: `0.6.9`
- Commit: `84ee50673804b95c287d1e4eb4f1c1dad7c5188a`
- Synced: 2026-09-16

The `vendor/agent-skills/` directory was synchronized from that release. These
Astakos-owned additions are retained and validated against the current schema:

- `skills/astakos-skill-authoring/SKILL.md`
- `evals/cases/astakos-skill-authoring.json`

Astakos-specific workflow policy belongs in the repository-root `AGENTS.md`,
not in the upstream repository's own `AGENTS.md`.

`scripts/validate-versions.js` reads the release above when run from this
vendored layout. In a standalone upstream checkout it continues to validate
against the latest Git release tag.
