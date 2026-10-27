# Routines, context and proactive conversation

This guide describes v2.8.0 (2026-10-09), including PR #238 and the installation
fixes in PR #240. See [release verification](release-readiness.md) for the evidence
and remaining deployment-specific observations.

## Context follows the conversation

Astakos interprets ordinary reports using the current message, bounded shared
owner history and the registered context schema. It reassesses related flags,
rather than updating only the one explicitly mentioned. A report of arriving at
work can change work, home absence and co-presence state when the evidence supports
those changes. Joint travel, uncertainty and future plans must remain distinct:
leaving home does not by itself prove that a companion stayed behind.

Selections are checked against source IDs, event times, freshness and the latest
stored state before persistence. Location proves the owner's whereabouts, not
another person's presence. These guards also apply to inferred related updates;
an older conversation turn cannot replace newer state.

When a required condition is unknown, Astakos can ask a context question. Replies
can also contain additional facts, memories or unrelated requests; they are not
restricted to a yes/no command. Interpretation depends on the configured model.
Offline regressions verify persistence and safety, not every live interpretation.

Current source (Unreleased) also reconciles explicitly reported work shifts from
live owner messages through the dated semantic schedule path, including reports
made at home after work. The live pass accepts only shift results; ordinary
presence remains owned by its source-validated writer. A repeated observation of
the same shift retains an existing later schedule expiry. An explicit dated
correction or cancellation can still change it. History and state-version guards
prevent a delayed live result from overwriting a newer decision.

Child-with-partner presence is not exclusive custody. A presence-only condition
that suppresses an activity when the child is with the partner does not suppress
it when effective evidence also confirms the child is with the owner. This is
shared condition evaluation for existing and future routines, independent of
routine names and channels. Unknown or stale owner co-presence does not grant
that exception. Other conditions, including extended absence, work, location and
already-started/completed activity state, still apply independently. Clarification
accounts for both child co-presence flags when evaluating these conditions.

Current source (Unreleased) uses bounded, trusted owner-day references for routine
feedback, so an earlier activity is not treated as skipped merely because a later
activity is mentioned. Completion follows the routine's purpose: actual play or
arrival for a visit can fulfil participation, while starting a task that requires
finishing does not. Intentions and generic location are insufficient.
One clear report can record two to five independent completions or today's
cancellations atomically. A completion in one clause does not discard a clear
cancellation in another. Weather alone or conditional plans cannot cancel a
routine. Each has its own validated identity/date; ambiguous variants require
clarification.
Batches cannot pause, acknowledge, reschedule, create drafts or authorize external
actions. A stale candidate/source or one failed write cancels the whole batch.
The reply acknowledges every recorded outcome, preserving prior delivery receipts.

The child outing state is interpreted from the current timed owner report through
the canonical context writer: in_progress means the outing actually began; done
ends that suppression when the child has returned. Plans remain distinct. Memory
summaries and legacy lexical outing rules cannot write this state or create its
suppression conditions. Existing conditions remain: suppression stops a reminder,
whereas a dated completion is a separate recorded outcome.

In current source (Unreleased), pre-question resolution can distinguish an
explicit ongoing duration from a momentary presence report. A grounded current-day
commitment may supply separate evidence until its stated end, capped at next local
midnight. The model must connect the duration to an actual current/completed
transition and consider every later report; a plan or two people working alone
does not prove separate locations. Shift names do not invent shift end times.
An applicable active daily schedule can supply an exact ending for an episode
grounded in today's owner reports. The selected routine identity, time, conditions
and schedule metadata are revalidated before persistence and when reading the
proof; a changed, paused, blocked or externally sourced schedule cannot sustain
it. Schedules alone never establish execution, presence or separation.
Schedule applicability rejects missing/unsupported condition types and uses
GPS-reconciled observations without consulting the duration proof itself.
Referenced boolean context observations outside the volatile set also retain
their freshness limits; date/shift conditions keep their own typed contracts.
Ordinary presence still expires after two hours. The original observation and its
timestamp stay unchanged; an internal proof uses the canonical conditional writer
without a schema migration. New trusted owner history or changed canonical state
(including GPS flag refreshes) invalidates the proof conservatively and requires
reassessment. Missing, corrupt or expired proof leaves ordinary clarification in
place. External action approval requirements are unaffected.

Web draft preparation, like Chat, can resolve a recipient from the bounded
conversation when the owner accepts a message offer without repeating the name.
Preparation still uses the canonical saved-draft tool. A bare send command without
an active draft cannot create a replacement; existing draft-edit isolation and
the separate external sending approval gate remain in place.
Ordinary contextual requests pass a bounded, tool-free semantic preparation
decision before the draft tool is offered. Declines, unrelated conversation and
externally sourced/synthetic input cannot supply that permission. Graph turns
capture the shared draft revision and trusted owner-history version before model
execution. Web, Matrix and Telegram attach the actual persisted owner row ID;
equal message wording cannot substitute a newer turn's identity. Missing or
mismatched IDs fail closed when trusted owner history exists.
The canonical writer checks both under a cross-process draft lock and
replaces the JSON atomically; a newer draft or owner turn rejects the delayed
write. Internal injected state is hidden from the model's tool schema. Drafts
include a unique revision even when their text and second-resolution times match.

Messenger routine notifications offer local preparation without presenting a
supposedly saved message. Chat/Web preparation must produce a native draft-write
receipt: a prose-only model answer gets one required-tool retry, then an explicit
failure if no write is requested. Successful writes display the saved tool result
without another synthesis call. For a missed mixed request, one bounded semantic
decision uses the candidate reply as untrusted reference and the owner turn as
the permission source. It replaces the earlier pre-generation semantic check,
so ordinary conversation does not pay for both checks. Pending-draft sends first
defer to preparation when the owner also requests a new draft. Recovery retains
the existing active-draft/contact boundary and excludes tool content from its
owner dialogue; same-turn external-content action guards remain authoritative. Preparation finishes before sending: any send call batched
with that write is removed, leaving the normal reviewed-draft approval path.
Bare send, declined preparation and explanatory questions cannot authorize a new
draft from an unsolicited candidate reply. The required-tool retry receives the candidate as
untrusted text reference, including after a Web failure. Historical tool messages
do not veto a new owner request, while an external result in the current turn
can still block its write through the existing approval guard.
Send requests for a stored draft enter the normal
external approval path; expired drafts cannot be sent or recreated by that request.
An owner can retire an unwanted draft through ordinary conversation, including
after expiry. Retirement checks the observed owner turn and draft revision under
the writer lock, preserves the remaining conversation, and supplies no routine
completion or skip evidence.

Approval records bind saved-draft sends to the observed revision. A replacement
requires a new approval; legacy unbound pending sends cannot adopt a current
draft. Dispatch claims that revision durably before transport work, so concurrent
approvals cannot send it twice. Successful delivery leaves a `sent` record; an
interrupted/failed transport leaves `sending` or `uncertain` and is never retried
automatically. The transport cannot prove exactly-once remote delivery after a
crash. Owner preparation can replace the claim; completion never deletes that
replacement. Guarded retirement serializes its owner-version check and file
replacement with SQLite history writers. Channel clear shortcuts use that same
guard. Matrix places trusted feedback receipts before the current owner turn.

## Read the routine status correctly

Pre-question daily inference uses a dedicated historical-resolution prompt rather
than replaying the latest report as a new message. Its structured event
`daily_context_resolution` distinguishes applied duration/observation proofs,
model uncertainty, rejected or superseded proposals, changed state, missing
sources and invalid output. It records flag identifiers and channel, not message
text or coordinates. Two-hour observation expiry and duration-proof validation
remain in force; a morning work plan alone cannot prove later co-presence.

| Debug field | Meaning |
| --- | --- |
| Active now | The current condition check allows the routine; this does not prove that its scheduled time has arrived or that a message was sent. |
| Suppressed / blocked | A known current condition prevents the routine action. |
| Rule: suppress when … | The configured rule, which remains present even when its condition is false or unknown. |
| Stored | The last recorded value, retained with its source and expiry. |
| Effective: null | The value is currently unknown, for example because its freshness window expired. |
| Last recorded decision | A scheduler decision or local context note, not necessarily a delivery receipt. |
| Active dated feedback policy | The dated ledger is in use for this routine; this does not mean that today's occurrence was delivered or completed. |

For example, `partner_with_user=true` may remain stored after expiry while its
effective value becomes unknown. The suppression rule is still configured, but
the expired value is not proof that the partner is currently present. Follow the
latest condition check and dated delivery evidence rather than the rule text alone.

## Delivery, acknowledgement and completion

In current source (Unreleased), explicitly scheduled reminders and their required
context questions can run during the usual fifteen-minute preparation window
even inside the default quiet-hour window. Default quiet hours still suppress
spontaneous conversation. A current explicit quiet request, mute or pause wins;
context, eligibility, delivery budgets and final currentness checks remain in
force. Missing context is not assumed false, and clarification does not ask after
the scheduled slot. A greeting alone does not establish the owner's location.
Optional context notes retain the ordinary quiet-hour policy, including notes
already prepared by reminder wording; they do not receive the scheduled exemption.

The dated policy records each routine occurrence separately. Actual delivery,
acknowledgement, refusal and completion have different meanings. A preparation
reply does not complete the activity. A later report that the activity happened
can complete the matching occurrence, including a historical occurrence when
supported by the conversation.

The shared semantic selector receives the routine catalogue, schedule,
conditions and bounded recorded engagement. This helps distinguish morning and
afternoon variants even after a preparation reminder expires. Explicit identity,
date and ambiguity remain relevant; new or changed catalogue evidence invalidates
a stale selection before it is saved.

Only delivered unanswered occurrences contribute to unanswered pressure.
Undelivered days are neutral. Three unanswered occurrences or three refusals
produce separate streaks; backoff progresses from 20 to 40 to at most 72 hours.
The Debug baseline is a historical starting point, not a claim about today's state.
Do not reset it merely to clear a display or rerun an upgrade.

**Activation:** normal routine database setup prepares the occurrence schema in
the same serialized transaction as the routine tables, including fresh installs
without a routine JSON file. Existing receipts, feedback, baselines and routine
settings are preserved. Runtime composition only loads the resulting compatible
store. First-run JSON import declares routines separately; no old deliveries or
completions are invented. See [release readiness](release-readiness.md).

## Optional notes and behavioral initiatives

A blocked routine may receive a relevant optional context note, subject to a
30% gate for that occurrence and the existing quiet/mute/pause safeguards. It
does not encourage the blocked action, mark completion or create unanswered
pressure. A work context is not a blanket ban on every conversational comment.

In Unreleased source, a semantic context skip leaves the occurrence undelivered
and eligible for reassessment within the existing fifteen-minute preparation
window. Wording is evaluated in at most four stages: every five minutes initially,
then once during the final minute before the slot. Reservations survive polling
and restarts. Current time and the
scheduled activity time are supplied separately: an earlier temporary activity
does not itself cancel or postpone today's routine. Normal delivery, completion
and current context checks still govern every attempted send.

When wording already supplies a context note, the existing note delivery path
reuses it rather than asking a second model to write another comment. The 30%
chance and one-note-per-occurrence limit still apply, including freshness,
silence, channel, budget and uncertain-delivery guards. A skipped comment is
not evidence that a reminder was delivered or the activity completed.
An empty generated note is rejected; internal diagnostic text never becomes a
prepared message.

Behavioral observations are a separate feature: recurring trusted reports can
support comments in ordinary replies and occasional spontaneous openers. Events,
pattern candidates and actual opener delivery are different evidence layers.
Identity resolution preserves specific entities and actions without reclassifying
old records automatically. Initial opener limits include one per day, a seven-day
topic cooldown and at least 15 minutes idle, plus existing delivery safeguards.
Both conversation selectors compare up to twelve qualifying patterns from the
last thirty days; an ordinary reply receives at most one selected observation.
A cached skipped initiative decision is reconsidered when its evidence changes,
including completed background intake,
but unchanged polls do not invoke the model again. An opener can express neutral
or positive interest without requiring a problem or advice opportunity.
Prior entity references include distinct-date support and stable source ordering
to help semantic extraction reuse established identities across languages. This
does not merge historical labels or let past classifications override a source.

Follow-ups are a different path: a conversation exchange creates a pending topic
that is checked later for a relevant continuation. Behavioral initiative needs
repeated observations on at least three distinct dates and starts a new topic;
it neither creates nor completes a pending follow-up. Both respect recent activity.
Both behavioral selectors read pending follow-up subjects and topics sent in
the last seven days, with bounded owner context, to avoid equivalent questions.
The initiative pins that snapshot through its pre-send freshness check. Reading
these topics does not initialize, modify or complete the follow-up queue.

Goals also remain separate. Conversational partial updates preserve recorded
activity and provenance; milestone scores do not invent completion percentages.
Follow-ups use recent relevant activity rather than an isolated old mention.
An owner update can close an existing follow-up without repeating its title or
place name. The resolver considers the original scenario and bounded dated owner
context in one shared model evaluation for up to twenty candidates; an unrelated
or ambiguous reply leaves it open. The complete batch is validated before any
write, rejecting unknown/duplicate IDs or malformed actions. A scheduler's structured
resolve/defer decision controls the outcome, never keywords in its explanation.
Automatic retries check again within an hour without renewing the existing expiry
or rolling an evening window into another day. Only a confident, explicit owner
postponement renews the timing and expiry. Updating an existing topic does not
reopen a sent or closed follow-up.
Manual deferral reports success only when the pending record actually changed;
a sent or concurrently closed record receives a no-change response.

Routine feedback also reads up to four adjacent assistant comments from the last
15 minutes, solely to understand the owner's response. These references cannot
act as delivered routine questions or grant permissions. Criticism of a comment's
timing or assumptions does not cancel an activity scheduled for later; a clear
independent cancellation or execution report still records its own outcome.
When no dated feedback was recorded, the graph receives that explicit result so
it must not invent an acknowledgement that a routine was skipped or completed.
That no-change notice is informational: normal draft and pending-action handling
continues through its existing approval gates. Recorded routine actions and
uncertain/error outcomes retain their existing turn ownership.

## Approvals and troubleshooting

External messaging retains its approval gate. In Matrix, use an exact **Reply**
to the approval request; reactions are not approval. A local draft or context
update is not proof that an external message was sent.

Read delivery receipts and dated records before diagnosing a missed routine.
A routine correction or historical completion repair requires its own scope;
changing documentation or code does not rewrite today's ledger. Start with
[the setup guide](../SETUP_GUIDE.md) for transport configuration and
[AGENTS.md](../AGENTS.md) for development boundaries.
