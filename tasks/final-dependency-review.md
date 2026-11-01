# Remaining dependency decisions — 2026-11-01

Integration baseline: 9d1fbe7470af9502ccf8bef09bf7904d29ac2689.
Scope: finish the four remaining Dependabot proposals without changing the Python
baseline, removing installed legacy SDKs, touching live data or publishing images.

## LangGraph #15

Update the range to >=1.2.19,<1.3.0, selecting the current compatible patch rather
than the old proposed minimum 1.2.9. Keep langchain-core==1.4.9.
Full current-manifest resolver verification succeeds with this range. Tested local
coordinated set: langgraph 1.2.19, checkpoint 4.3.1, prebuilt 1.1.1, SDK 0.4.11,
and langchain 1.3.14. Updating the installed langchain package preserves its legacy
langchain-google-community dependent; that package is not a new application
dependency. No application imports of that old integration were found.
All candidate packages support Python >=3.10, including the release Python 3.11.
Candidate-overlay pip check reports no broken requirements. tzdata was not
upgraded merely because the dry-run resolver offered a newer allowed release.
After fixing the obsolete/non-hermetic test contracts below, the same 183 focused
offline graph, Messenger, approval, registry and Web-budget cases pass with both
baseline and candidate dependencies. Outbound transport is blocked, native stores
are temporary, and the production graph has no persistent checkpointer to migrate.

One existing approval test imported _draft_edit_tools_only, which PR268 deliberately
removed. Its ImportError reproduces with baseline dependencies. Replace that stale
contract with the current canonical primary-preparation boundary and native draft
persistence: sibling tools remain, batched send is removed, draft remains pending
and no approval/send is created by preparation. No production guard is weakened.
Three structured-decision cases now explicitly choose their synthetic Matrix
channel; a draft-state case explicitly supplies synthetic contacts. This removes
dependence on the owner's .env/contact settings in isolated worktrees.

## Closed without merging

- #16 NumPy 2.5.1 requires Python >=3.12, while Dockerfile.release uses 3.11 and
  current NumPy 2.4.6 supports 3.11. Keep 2.4.6; do not broaden this maintenance
  task into a Python/Docker baseline migration.
- #18 google-cloud-aiplatform was intentionally removed in commit 2018c2c on
  2026-09-05; current providers use google-genai. The proposal is obsolete.
- #17 protobuf 7.35.1 conflicts with installed google-generativeai 0.8.6 and its
  google-ai-generativelanguage 0.6.15 dependency, which requires protobuf<6.
  An actual pip dry run fails ResolutionImpossible. Other installed Google/gRPC/
  OpenTelemetry packages also need coordinated updates for 7. Keep tested 5.29.6;
  do not uninstall legacy packages or force an incompatible runtime to empty the
  PR list. A fresh-install-only subset may resolve, which does not prove that the
  current installed environment can safely accept a standalone pin change.

All review categories on these four PRs were retrieved with pagination. No inline
or top-level code findings existed, only missing-security-label notices.
Repository open security alerts inspected during this pass target ChromaDB with
no patched version listed; they are not resolved by these four proposals. No
claim is made that an empty PR queue means an empty security-alert queue.
