# Semantic follow-up lifecycle

Authorized 2026-10-19: fix two stale conversational follow-ups, then inspect the
behavioral park opener and the owner's corrections. No live data repair, external
test messages, config, runtime or release changes.

## Evidence

- Wedding follow-up #463 (Oct 17) remained pending after two deferrals. Its saved
  explanation said the wedding happened yesterday evening and was already
  discussed/completed. The scheduler interpreted explanation words before the
  structured resolve action.
- Coffee outing #466 (Oct 18) remained pending despite the owner's 22:10 return
  update. Resolution required lexical overlap with the outing title before LLM
  evaluation. Automatic deferral reapplied an evening window relative to now and
  extended expiry, carrying old events into later evenings.
- Behavioral opener Oct 16 15:11 asked about frequent park visits. At 15:13 the
  owner corrected that he was at work in Efkarpia; the reply incorrectly claimed
  to record the day's park routine as skipped. At 15:14 he challenged the timing again.
  The delivery ledger's context had user_at_work=false. The owner clarified on
  Oct 19 that he had misread "ευκαιρία" as "Ευκαρπία" and accepted the opener as
  correct. No geographical error or behavioral selector repair is established
  by that misunderstanding. The owner subsequently requested the separate repair
  of the response that treated his correction as a routine skip, in this PR.
  Routine historical feedback is not rewritten here.
  The final canonical park occurrence is complete at Oct 16 18:44, after the
  owner reported arrival. The persisted opener and park observation rows do not
  name Efkarpia as a park location, consistent with the owner's clarification.

## Acceptance and implementation

1. A structured resolve cannot be overridden by explanation wording; missing or
   invalid skip actions cannot invent a transition. Departure safety remains.
2. Completion updates reach the semantic resolver without a phrase/title gate.
   Bounded preceding owner context clarifies references, excluding external data,
   later messages and context older than 24 hours. Completion takes precedence
   over timing-only postponement; ambiguity and invalid/weak decisions fail closed.
3. Automatic retries stay within an hour of a due check, retain existing expiry
   and expire rather than extending past it. Explicit owner postponement retains
   the existing semantic scheduling/renewal API. Inactive records never reopen.
4. Regression tests use isolated storage, fail all unstubbed outbound/model calls,
   and assert final persisted states, not only mocked intermediate decisions.

## Verification

Initial new-case run: 9 failed / 4 passed before the fix. Focused follow-up group
after the first implementation: 95 passed. Final related group: 163 passed
(follow-up lifecycle, scheduler safety, multimodal parsing, behavioral/follow-up
separation, Web context wiring, Telegram routing and routine tools). An isolated
in-memory mutation disabling the structured resolve branch made the wedding
regression fail; production sources were not mutated. git diff --check passed.
No claim of live LLM semantic verification or full repository suite coverage.
Both existing owner follow-ups and routine feedback were left untouched manually.

## Comment corrections versus routine outcomes (authorized after PR creation)

The dated feedback reference loader included owner reports and authenticated
routine context questions, but omitted the adjacent Behavioral_Agent opener.
It now supplies up to four assistant utterances from the preceding 15 minutes
as conversation_reference data only. External, future, oversized and forged
routine-question references are excluded. Canonical question correlation and
permissions remain separate. The semantic policy distinguishes correction of
commentary from a current cancellation or actual execution report.

Previously a no-feedback result supplied no graph context at all. The graph now
receives the explicit status/action none receipt, with no routine identity or date,
and must not claim a stored routine change without a separate successful current
canonical tool result. This also covers truthful replies when no database change
occurred. The old trace shows only a memory-save tool, which does not establish a
routine skip; pre-graph feedback was not included in that trace.

New correction suite: 13 cases failed before the fix and passed afterward,
covering the reported wording across Web, Matrix and Telegram, explicit
cancellation, actual arrival and unsafe reference exclusion. Full related
verification for this additional slice is recorded below.

No-action notices carry canonical non-consuming metadata. Web, Telegram and
Matrix use one shared helper to keep existing draft/pending flows reachable;
errors, stale results and concrete routine results retain their consuming
behavior. New channel regressions reproduced and caught the initial blocking
of Web/Telegram pending lookup and Matrix draft preview/clear. Existing approval
and external-send gates remain on their normal paths.

Additional verification: 595 related cases passed; after adding the canonical
non-consuming receipt metadata, the final channel/receipt group passed 150 cases.
The groups cover 732 distinct offline cases (13 correction cases overlap).
The no-feedback mutation was caught by both exact correction cases while real
cancellation and arrival continued to pass. git diff --check passed. No live
model interpretation, outbound send or historical ledger repair was performed.

## Codex review corrections (e9d5b92)

- Inline comment 4312384089, P1: reproduced twenty serial provider calls with
  twenty unrelated active candidates. Completion/deferral now share one strict
  bounded batch selector; no per-record inference remains. Provider failure,
  malformed data, unknown/duplicate IDs and conflicting actions leave the batch
  unchanged. Low-confidence valid actions are omitted. Legacy single-record
  classifiers/prompts were retired and their regressions moved to the provider
  boundary so the batch parser and final writes remain real.
- Inline comment 4312384093, P2: reproduced manual defer returning a success for
  a sent record despite unchanged timestamps. The tool now propagates a rejected
  defer result, including a status change after lookup, without claiming success.

First focused group after correction: 126 passed. Final checks follow below.
Final related group: 176 passed, including twenty-candidate one-call behavior,
mixed resolve/defer persistence, invalid-batch no-partial-write protection,
empty-queue zero-call behavior, manual rejection and a lookup/write status race.
Two isolated in-memory mutations (duplicate classification and ignored manual
rejection) were both caught. git diff --check passed; live data was not changed.

## Expiry bookkeeping review correction (22500e4)

Inline 4312615609, P2: reproduced an automatic retry expiring after model
evaluation with resolved_at unset and outcome_score unchanged. Automatic and
scheduled expiry now share an atomic lifecycle/outcome write, conditional on the
observed active status and deadline. Repeated expiry does not charge twice, and
an intervening explicit owner renewal is preserved. Regression assertions inspect
the final isolated persisted timestamp and score; no live rows are repaired.
Final related group: 180 passed. git diff --check passed. Live model calls and
the full repository suite were not run for this narrow correction.
