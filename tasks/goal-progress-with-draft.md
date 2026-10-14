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
  core/approval.py implementation at the initial PR head was byte-for-byte identical to main. Its old
  transport mocks cannot deliver through the selected external approval router;
  the secure runtime correctly blocks when delivery fails. No approval-source
  changes or unrelated test repairs were bundled into the initial goal fix.
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

## Review repair (2026-10-14)

Owner authorized addressing completed Codex review 5515567505 at head 21084e2.
Inline 4268836322: all new test functions and nested model methods now have type
hints and docstrings. Inline 4268836328: older external provenance can defer the
milestone update while the independently authorized local draft is safe. The
existing graph stopped before ToolNode, dropping that draft entirely.

Reproduced with the actual graph, canonical approval policy, temporary native
draft/pending persistence and the native goal updater: disabling the new helper
in memory made both call orders fail with only the goal queued and no draft.
Production source and live stores were not mutated during this reproduction.

After the full batch passes existing blocking gates, preserve only the exact
two-call draft/milestone pair with distinct IDs and only the milestone critical.
Recheck the draft with the canonical approval policy and execute it through the
native ToolNode. The milestone stays pending with external provenance; later
approval executes only that milestone. Report actual draft preparation/error and
pending approval separately. Consume a routine offer only on the native success
receipt. Other tool batches, sends, fresh external actions and read-only diagnosis
retain the existing stop behavior. Tests isolate provider classification and
transport boundaries; they verify final persisted outcomes, not live inference.

Ten additional graph cases cover both call orders, final receipt IDs/text, later
approval, fresh external content, missing owner request, a third send, read-only
diagnosis, duplicate IDs, local storage failure, approval delivery failure and
accepted-offer consumption. AST inspection confirms annotations/docstrings for
every new function; Python source compilation and diff checks pass.

The affected approval/goal/draft group passed 207 distinct cases. Twenty failures
in test_plan_mode_approval.py reproduce against main's approval implementation
loaded in memory, with network denied: the old tests mock _notify_telegram instead
of the selected-channel boundary and expect pending after delivery failure.
They remain outside scope, alongside the seven previously documented draft-test
failures. A fully socket-guarded run passed 206 cases; the Windows spawn test
requires a real pytest entry point rather than a stdin-hosted pytest harness.
It is verified separately through the normal venv pytest command. No live store
was changed during these review repairs.
