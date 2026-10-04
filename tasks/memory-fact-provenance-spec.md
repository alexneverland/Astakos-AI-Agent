# User-fact provenance and same-period duplicates

## Contract

Assistant acknowledgements are not user facts. The deterministic confirmation
writer may store only a payload explicitly supplied by the user. Contextual
references remain the semantic sifter's responsibility. No new phrase lists or
global embedding threshold changes are introduced.

The canonical memory manager compares up to five embedding-near USER_FACT records
across categories. One model comparison establishes equivalence of subject,
meaning and effective period; category or translation alone is not new information.
Recording dates help resolve relative periods but are not event dates. Different
periods, changed states, added details and uncertain comparisons are not declared
duplicates. Existing storage policy remains the fallback, including when semantic
comparison is unavailable. Assets and external-provenance facts are excluded.

The model runs outside storage locks. A duplicate verdict is applied only after
rechecking the selected record's identity, text and temporal/provenance metadata
under the normal write locks. This repair adds no deletion of stored facts.
Simultaneous first writers that both see an empty snapshot are not guaranteed to
collapse into one record; this is bounded duplicate prevention, not a migration or
a globally atomic semantic uniqueness constraint.

Debug labels embedding distance as `distance`, not similarity. `add_alongside`
records a storage decision; the corresponding `add` records the actual insertion.

## Verification and exclusions

Offline regression reproduces the reported acknowledgement pollution and the
Greek/English shift fact in different categories. Tests exercise final synthetic
vector records and isolated profile storage, distinct weeks, failed/invalid model
responses, and record changes during classification. Tool-then-sifter orchestration
is covered without live providers or user data. Stored photo-backed records are
excluded from comparison, and photo provenance is revalidated after classification;
both initial asset provenance and a concurrent provenance change have regressions.

No cleanup of existing memories, original Chroma inspection, configuration,
credentials, runtime changes, or full test-suite run. Natural model interpretation
and the additional background-call latency remain live observations, not proven
by mocked model responses. The model comparison is a single attempt, not a retry
loop. It does not introduce a new followup or behavioral-pattern mechanism.
