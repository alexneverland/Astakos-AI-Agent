# Shift reconciliation: recording dates versus effective periods

## Evidence and contract

On 2026-10-04 the event log recorded an afternoon shift through 2026-10-09,
then another write ten seconds later expiring on 2026-10-04. Monday's scheduler
therefore resolved the shift as unknown. The dated courtesy memory and the
legacy fallback's use of the first ISO date explain this expiry regression;
this is not evidence of a general Monday reset or deletion of stored memories.

The existing semantic routine extractor owns dated shift interpretation. A valid
semantic current_shift decision takes precedence over the fallback, which must
not write a second expiry for that same key. A fact containing ISO dates cannot
use the legacy phrase-based shift-state fallback: recording and effective dates
cannot safely be distinguished there. No new phrase lists are introduced.

Validate structured shift values and canonical, non-expired ISO end dates. An
uncertain dated statement or model failure leaves the existing schedule unchanged.
The model distinguishes weekly schedules, individual days, recording dates,
acknowledgements and explicit corrections. Do not unconditionally keep the
longest expiry; that would prevent genuine corrections.

An explicit current cancellation uses context_operation=clear with an explicitly
present null/empty context_value. Missing values or uncertain observations do not
clear state. The canonical persistence path stores an empty shift; the resolver
then returns no weekday shift. A cancellation may omit its end date; any supplied
date must still be canonical and non-expired. Historical/future cancellations
are not current clear decisions. No cancellation phrase lists are introduced.

Canonical semantic ownership/work-domain mapping is sufficient for shift scoring;
it does not require a literal owner name or language-specific alias in the fact.
Undated legacy fallback behavior and existing routine-condition handling remain
unchanged. This scoped fix does not redesign the daily context extractor, add
future schedule storage, migrate memories, or alter scheduler/runtime settings.

## Verification

Offline regressions use real reconciliation, isolated routine persistence and the
actual shift resolver across the Sunday/Monday boundary. Only the model and event
log boundaries are replaced. Cases include the reported dated courtesy input,
weekly/daily precedence, uncertainty, model failure, invalid dates/values,
explicit shortening and implicit-owner night shifts. Legacy rule/scoring tests
explicitly disable cloud extraction instead of relying on provider failure.

Verification: 122 focused tests pass, Python syntax compilation and diff checks
are clean. No full suite was run.

The deterministic lifecycle is covered; actual model interpretation and subsequent
natural state updates still need live observation. No real database or Chroma
access, data cleanup, credentials/configuration edits or full-suite execution.
