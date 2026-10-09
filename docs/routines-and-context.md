# Routines, context and proactive conversation

This guide describes `main` after PR #238 (2026-10-09). The latest published
release is still v2.7.0; see [release readiness](release-readiness.md) before
assuming these changes are in a downloaded release image.

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

## Read the routine status correctly

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

Behavioral observations are a separate feature: recurring trusted reports can
support comments in ordinary replies and occasional spontaneous openers. Events,
pattern candidates and actual opener delivery are different evidence layers.
Identity resolution preserves specific entities and actions without reclassifying
old records automatically. Initial opener limits include one per day, a seven-day
topic cooldown and at least 15 minutes idle, plus existing delivery safeguards.

Goals also remain separate. Conversational partial updates preserve recorded
activity and provenance; milestone scores do not invent completion percentages.
Follow-ups use recent relevant activity rather than an isolated old mention.

## Approvals and troubleshooting

External messaging retains its approval gate. In Matrix, use an exact **Reply**
to the approval request; reactions are not approval. A local draft or context
update is not proof that an external message was sent.

Read delivery receipts and dated records before diagnosing a missed routine.
A routine correction or historical completion repair requires its own scope;
changing documentation or code does not rewrite today's ledger. Start with
[the setup guide](../SETUP_GUIDE.md) for transport configuration and
[AGENTS.md](../AGENTS.md) for development boundaries.
