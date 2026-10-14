# Goal progress alongside draft preparation (2026-10-14)

Owner approved fixing conversational Kaggle progress persistence. At 10:48 the
owner reported score 0.12 and requested a local Messenger draft. The Web agent
prepared the draft but never called a goal update. Debug still showed the goal's
original 0.06 description; the memory sifter saved 0.12 as a separate project fact.

Root cause: Web lacks goal milestone updates, and both Chat/Web draft-creation
gates reduce tool bindings to relay_local_payload. Existing Chat/Dev goal tools
and semantic goal context already support partial updates preserving history.

Scope: allow only the existing milestone updater alongside reversible draft
creation/acceptance, and expose it to ordinary Web conversations. Preserve the
strict active-draft revision isolation and keep sends, research, goal creation,
status/progress mutation and registry extras outside the restricted draft path.
Scores remain milestones, not percentages. Resolve existing goals semantically
from current owner reports and supplied context, preserving prior relevant results.

Acceptance: exact compound report can persist 0.12 through the native goal tool,
then Debug and goal-followup readers expose it; original description, percentage,
status and creation time remain intact. Ambiguous/unknown projects, untrusted
sources and failed tools cannot claim success. Existing send approval/provenance
guards and active-edit isolation remain unchanged. No phrase-list matching.

Plan: reproduce missing binding; narrowly extend creation bindings and Web's
semantic instructions; test final native goal persistence/readback, registry
filtering, active edits and approval safeguards; update docs/Unreleased.

Test: venv\Scripts\python.exe -m pytest tests/test_goal_progress_with_draft.py -q
--basetemp=.pytest_tmp_goal_progress_draft

No migration, config/credentials, runtime/watchdog, release or subagents.
Provider inference and outbound transport remain offline in tests. A manually
bound tool test is not evidence of every future provider's semantic choice.

## Verification (2026-10-14)

- RED: four Chat/Web creation/accepted-offer cases lacked the milestone binding;
  two active-revision isolation cases passed. GREEN follows the actual bound
  tool through native goal persistence, then Debug and followup readers.
- Ten new cases cover native readback, preserved percentage/status/creation time,
  event history, registry extras, strict active edits, ordinary Web availability,
  unknown project/storage failure, and external-source approval/provenance.
- Affected goal/approval/draft/tool/research group: 192 passed, two existing
  dependency deprecation warnings. Python compilation and diff checks passed.
- A broader run added test_draft_authorization.py: 206 passed, seven failed.
  That file alone reproduces the same seven failures (14 passed), and its
  core/approval.py implementation is byte-for-byte identical to main. Its old
  transport mocks cannot deliver through the selected external approval router;
  the secure runtime correctly blocks when delivery fails. No approval-source
  changes or unrelated test repairs were bundled into this goal fix.
- In-memory mutation removing post-registry filtering failed the active-edit
  regression, exposing milestone and external-extra tools. Source was unchanged.
- README and Unreleased describe milestone readback and the retained boundaries.

Owner subsequently authorized updating the existing Kaggle card and opening a
PR. The native milestone updater recorded the 2026-10-14 owner score 0.12 with
the previous 0.06 result retained. Independent live /debug/goals readback and
the followup formatter expose the new milestone. Original description, status,
percentage, goal date and creation metadata were verified unchanged. No other
live data was changed. Future reports use the same partial updater. PR creation
is authorized; merge, branch deletion and review monitoring are not requested.
