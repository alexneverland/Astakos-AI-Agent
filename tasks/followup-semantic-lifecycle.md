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
  by that misunderstanding. Behavioral behavior is outside this follow-up patch;
  routine historical feedback is not rewritten here.
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
