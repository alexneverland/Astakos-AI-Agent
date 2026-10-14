# Reviewed memory maintenance retirement

Owner authorized cleanup, retirement of unsafe tools, PR review corrections,
and merge/delete after checks on 2026-10-14. No subagents.

## Review correction: canonical ID-specific deletion

Objective: provide the exact audited operation promised by the maintenance docs.
Add `memory.maintenance.delete_reviewed_memories`, using the existing managed
Chroma get/delete primitives and native audit journal. Do not route through
free-text deletion or touch structured profile facts, history or assets.

Contract: require explicit owner authorization and an active maintenance pause;
reject unsupported collection, duplicate IDs, changed document/metadata or
missing retained IDs. The caller must retain a verified cold backup and control
new launcher starts. Persist a strict audit intent before deletion, fail closed
if audit cannot be written, verify every remaining document/metadata pair, then
write the completion receipt. Preserve intent and signal uncertainty if final
verification/audit fails. Keep this operator API out of LLM tool bindings.

Files: `memory/maintenance.py`, minimal audit return-status/strict-log support in
`memory/vector_store.py`, `tests/test_memory_maintenance.py`, maintenance docs.
Style: typed Python functions, explicit errors, no linguistic heuristics.

Plan: reproduce the missing API contract offline; implement one complete deletion
slice; run real temporary-Chroma lifecycle tests with transport disabled, review
the scoped diff, commit/push, and obtain one final Codex review for this material
correction. Commands: `venv\Scripts\python.exe -m pytest tests/test_memory_maintenance.py
tests/test_clean_memory_audit.py tests/test_daily_data_backup.py tests/test_memory_audit_log.py -q`;
`git diff --check`.

- [x] Exact deletion and durable audit intent/completion verified on temporary Chroma.
- [x] Failure gates preserve records; profile and unselected records remain unchanged.
- [x] Docs call the canonical operation; focused tests and diff checks pass.
Final review and merge status are tracked in PR #254, outside this historical spec.
