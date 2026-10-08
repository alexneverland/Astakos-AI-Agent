# Spec: Behavioral entity identity repair

Status: implemented and offline verified after owner approval, including general
identity/action disambiguation, not a pet-specific exception. PR #236 merged
on 2026-10-08; its task branch was deleted. Live semantic observation remains pending.

## Objective and acceptance criteria

Repair the existing shared behavioral intake, not routines or follow-ups.
References in different languages must resolve to the
same entity when trusted context supports that identity. Interpret the reported
action separately: cleaning, feeding and cooking must not become one behavior.

- Semantically equivalent references to one pet reuse one canonical item
  identity across Web, Matrix and Telegram. Do not add synonym/phrase lists.
- Context-supported pet care is not food preparation. Genuine food preparation,
  a different animal, plans, negation and uncertain references remain distinct.
- Persisted new events and the actual evidence/aggregation output demonstrate
  the repair; prompt assertions or mocked aggregation alone are insufficient.

## Existing structure and implementation boundary

Reuse `services/behavioral_event_extractor.py`, the canonical pattern key in
`services/behavioral_pattern_aggregator.py`, and the observational storage
abstraction in `memory/behavioral_event_state.py`. Retain the current item and
action-kind storage contract; no schema migration or second registry.

Give semantic extraction bounded, provenance-filtered identity references and
trusted conversation context. Existing observations are fallible reference
data, never instructions or proof that a previous classification was correct.
Any model-selected existing reference must be validated against the supplied
bounded references before persistence. Unknown/ambiguous identity must not be
forced into a known entity. Source messages and their dates remain authoritative
for whether an event happened, independently of historical identity context.

Use at most 40 unique prior observational references, with text fields bounded
to 160 characters, and 12 preceding trusted owner messages (500 characters each)
from a bounded 40-message shared-history window. Exclude later source rowids.
Skip oversized context messages rather than interpreting truncated statements.
The model may select nullable integer `item_ref` and `behavior_ref` indices.
The resolver copies only canonical item identity, or the specific event type
for an exactly matching subject/item/action kind; it never copies occurrence
dates, status, confidence or truth flags from reference data.

Specific event type becomes part of pattern identity, alongside subject, item
and action kind. Equivalent action wording reuses the model-selected canonical
behavior reference; broad categories are display only for named observations.
Retain the broader existing topic identity for initiative suppression, so this
grouping refinement cannot erase an existing seven-day cooldown.
If the existing fields cannot safely represent the distinction,
stop and discuss it rather than silently adding a migration or storage encoding.

## Code style and test strategy

Use typed Python functions and existing abstractions, for example
`normalize_extracted_event(extraction, source)`. Deterministic code validates
structured references and safety boundaries; the model interprets meaning.

Use pytest and isolated temporary observational/history stores. Replace only
provider/transport boundaries; prohibit live outbound calls. Reproduce alias
fragmentation first, then verify stored events reach a single eligible pattern
on three distinct days. Verify cleaning versus feeding, pet versus food,
different pets, absent context, untrusted references and malformed selections.
Offline tests prove the contract and persistence, not future model accuracy.

## Commands

Focused verification (extend only with directly related identity tests):

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_behavioral_event_extractor.py tests/test_behavioral_event_state.py tests/test_behavioral_pattern_aggregator.py tests/test_behavioral_conversation_evidence.py -q
.\venv\Scripts\python.exe -m py_compile services/behavioral_event_extractor.py services/behavioral_pattern_aggregator.py
git diff --check
```

No full-suite rerun by default, per the owner's standing request.

## Boundaries and verification status

Always: reproduce before repair; preserve provenance, source dates, deduplication
and existing distinct-day eligibility. Keep initiative limits and delivery intact.
Ask first: schema changes, additional dependencies or repair of historical data.
Never: phrase lists, automatic reclassification/backfill of live observations,
direct raw-SQL data edits, Chroma access, credentials/config/runtime changes,
new scheduler, live test messages, commit/push/PR without the owner's request.

The initial audit found persisted `food_preparation` / `prepare` observations
with item `rabbit`, and separate `rabbit` / Greek item spellings. The owner
confirmed these references concern their pet. The precise source wording and
the context/reference contract are covered by focused offline provider-boundary
fixtures and real temporary persistence, not a live semantic-model reproduction.
Historical misclassifications remain unchanged in this slice; natural live
semantic observation follows implementation separately.

Read-only compatibility inspection of the unchanged 111 confirmed observations
found four broad legacy patterns and three specific-behavior patterns. Existing
taxonomy variations can lose eligibility under stricter grouping; no historical
merging or reclassification is implied. Newly extracted equivalent actions use
the validated canonical reference to avoid further label fragmentation.

Verification: 13 RED cases before repair; final related run 175 passed with one
existing Google dependency warning. Changed Python files compile; whitespace
checks pass. Provider calls were replaced only at the test boundary. A boolean-
index guard mutation was exercised in memory, without modifying runtime source.
