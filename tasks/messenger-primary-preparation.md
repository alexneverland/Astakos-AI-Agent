# Primary-agent Messenger preparation

Owner approved 2026-10-30: replace the broad post-generation preparation
classifier, rather than deleting recovery and reintroducing mixed-request loss.

Contract: Chat/Web expose reversible native relay_local_payload during trusted
owner turns, including mixed requests, without phrase recognition as a binding
prerequisite. The primary generation decides intent through tool selection.
Native direct-owner provenance, draft/history CAS, identity resolution and
active-turn external-result guards validate writes. Sending remains separate,
revision-bound, approved, and cannot accompany a draft creation in one batch.
Old/stale sends retain canonical inactive-draft handling without regeneration.

No extra semantic preparation model calls, cache, timeout wrapper or recovery
prompt remain in the normal Chat/Web path. Pending existing-draft lifecycle
interpretation is distinct and remains scoped to actual pending draft state.
Local preparation never grants transport permission. A model choosing no tool
cannot establish a persisted draft: use native receipt rendering and existing
claim sanitization. No claim that inference accuracy is proven offline.

Slices: primary tool binding and guarded selection regression; eliminate recovery
and old artifact references; mixed/sibling/external/supersession/approval tests;
docs and diff verification. Use existing pytest offline guards, native temporary
stores and blocked outbound. No credentials, config, live data, watchdog or
runtime edits. New PR only when requested.

Preserved safeguards: explicitly recognized creation, routine offer and active
edit paths still enforce a native tool result through one required-tool retry
when the provider ignores the writer. This correction is conditional on those
existing paths and does not reclassify general conversation. Pending-draft
retirement keeps its existing semantic lifecycle helper; a send verdict now
returns to primary generation rather than running another preparation helper.

Tests that formerly simulated a forced draft only after a classifier now select
the already-bound writer in the primary model double. Assertions still inspect
actual saved content/revision, supersession, external-content rejection, pending
approvals and native receipts. Binding is no longer a synonym for semantic
permission: negative dialogue doubles choose no writer, while malicious tool
calls are tested independently against native provenance and freshness gates.
This changes local preparation selection policy, not external-send authority.

## Verification (2026-10-30)

- 173 focused Messenger/receipt/Web failure/mirror tests passed; 100 distinct
  approval, native draft, intent, timing and Web-budget tests passed; 105 other
  external-content tests passed. One added isolated-writer regression then
  passed in the affected 78-case group. A final primary-send replacement
  regression brings the total to 380 distinct passing cases. Entry guards now
  carry the revision captured under the native draft lock; primary sends bind
  that original revision instead of adopting a replacement after inference.
- The old broad recovery selectors were migrated to primary tool-selection
  outcomes, not dropped to hide failures. The exact mixed wording remains in
  graph tests; draft/send batches, malformed provider metadata, pending revision
  approval, old/sent revisions and replacement races retain native assertions.
  Conditional required-tool correction still fails visibly when ignored.
- One pre-existing Telegram photo test fails: FakeTrace lacks `error` in
  test_photo_reply_uses_current_asset_provenance_only. Reproduced in a separate
  process loading unchanged main production sources at
  2ca102d7c661e06e41a4aaeea0fefbf0bcecb029, without workspace replacement.
  Left outside this slice. No full-suite green claim.
- No live provider, real outgoing message or owner store was used for tests.
  Actual LLM recognition and live latency must be observed after review.
- Production search confirms no recover_preparation_reason,
  invoke_messenger_decision, resolve_contextual_draft_request, preparation
  decision cache or old preparation-classifier prompt references remain.
  git diff --check passed. Owner subsequently authorized commit/push/PR and one
  Codex review if no automatic review starts; branch is
  codex/messenger-primary-preparation. No merge/deletion authorization yet.

## PR268 Codex review repair

Finding 4424617015 (P1) reproduced against 2c27ebc: primary send normalization
preserved model-supplied target_name/message beside the native revision. Native
pipeline treats those fields as a direct-send override, bypassing the stored
draft claim. Three offline native graph/approval/pipeline cases failed before
repair: unchanged sends used the wrong text/recipient; replacement and retirement
after approval still reached the fake browser send.

Primary stored-draft calls now allow only expected_draft_revision from the
entry guard, discarding all model-supplied arguments for that call. No global
pipeline API or unrelated direct-send policy changes. Tests restore the native
pipeline from the fixture but replace Playwright and sleeps, retaining blocked
outbound and isolated stores. Covers both overrides and either alone, combined
with unchanged, replaced, retired and expired drafts after approval. The positive
control sends exactly the reviewed native recipient/text and marks its revision
sent; invalidated cases never start Playwright and preserve replacement state.

Verification: 95 related cases passed, followed by all 12 expanded native
override cases (three overlap), i.e. 104 distinct cases for this repair and 392
distinct relevant passing cases across the PR. git diff --check passed.
