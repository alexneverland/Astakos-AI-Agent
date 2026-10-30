# Shift provider content repair (2026-10-30)

Owner approved fixing weekly shift persistence. Native readback retained morning
from the 2026-10-28 11:04 report but expires_at was 2026-10-28, despite the report
explicitly saying this week. No later shift write or successful semantic weekly
receipt was found. Expiry projection, not a nightly delete, explains effective
null on October 29/30. The exact original provider response was not retained.

Confirmed offline defect: _safe_json_list accepts a scalar JSON string but
silently discards the same JSON in provider text blocks, because it passes a
list to a string-only parser and catches the TypeError. The ordinary extractor
already normalizes these blocks and can persist a daily shift before the
schedule pass silently loses its result. Installed langchain-google-genai
4.2.7 supports structured content. This is a concrete reproducible path, not
proof of the original unrecorded model response.

Scope: reuse canonical provider-text normalization at the reconciler boundary,
retain existing semantic date/schedule interpretation and revision/CAS/history
guards. No phrase lists, Friday guessing, TTL increases or global provider/parser
changes. Weekly reports retain their semantic Friday endpoint; explicit single-day
reports retain today. Do not manually repair live shift state, replay old owner
messages to a model, change config/runtime or create a PR without instruction.

Ordered checks: write native-store full-path regression for exact Wednesday
wording; vary provider content shapes and weekly/single-day/cancel/invalid cases;
assert correct effective shift on Friday and expiry on Saturday. Reproduce RED,
normalize at the existing boundary, run focused context/reconciler/shift tests,
compile and git diff --check. Update documentation and Unreleased notes.

Commands: `venv\Scripts\python.exe -m pytest tests/test_shift_provider_content.py
-q --basetemp=.pytest_tmp_shift_provider`; `git diff --check`.
Tests use isolated native stores and blocked provider/transport boundaries.
Offline fixtures verify persisted outcomes, not live model semantic quality.

## Verification

The installed client chooses type=text blocks when the model is Gemini 3 or
later, or text has a thought signature (chat_models.py response conversion).
The configured class is ChatGoogleGenerativeAI; only class/output-version/package
metadata and source were inspected, with no provider request or config changes.

Thirteen new offline cases exercise the exact Wednesday report through native
history, ordinary daily observation, semantic reconciliation/scoring, CAS and the
final shift resolver. Scalar, text-block, split-block and thinking-plus-text
responses retain the correct end date. Non-answer blocks/malformed JSON/invalid
dates preserve existing state. After correcting the test's initial assumption
about weekends (the established policy returns off, not unknown), RED reproduced
three weekly text-block failures while ten scalar/daily/safety cases passed.

The production change normalizes only at the existing reconciler provider
boundary, reusing core.ai_provider.normalize_provider_text_content. No shared
parser, provider configuration or expiry policy was changed. GREEN: 79 shift
and temporal-provenance cases plus 320 context/reconciler/evidence/clarification
cases passed (399 distinct), including existing schedule cancellation/revision
and source/state-race tests. Outbound was blocked; two existing dependency
deprecation warnings remain. Compilation and git diff --check pass.

Friday remains inclusive; Saturday uses the existing off policy, and an expired
shift does not return on Monday. No live data repair, cloud call, commit, push
or PR creation occurred. The old expired record therefore remains unchanged
until an explicitly authorized repair or a fresh owner report is processed.

## Subsequent owner authorization

The owner explicitly requested correction of the live record and PR publication.
On October 30, native context/history APIs verified the exact morning record
from October 28 11:04:10+02:00 and no later shift report (latest owner row 8089).
Under the history-version guard and native CAS, only expires_at changed from
2026-10-28 to 2026-10-30. The original source timestamp was preserved rather than
inventing fresh presence evidence. Readback verified the complete record and
effective morning shift. A bounded owner_authorized_shift_expiry_repair event
records this repair. No other context, routine, baseline, credentials or runtime
was manually changed. Scoped commit/push/PR are now authorized; merge, branch
deletion and review polling remain separate actions.

## Review repair authorization

Owner authorized review repairs after complete review retrieval at 616bee0.
Codex 4420911645: valid shift JSON in non-answer reasoning/tool_result text can
currently reach persistence. Sourcery 4420902686: joining answer fragments with
spaces alters JSON strings such as morning. Reproduce both with native stores;
replace the general display normalizer at this structured-output boundary with
an answer-only, lossless assembler. Keep shared display normalization unchanged.

Sourcery 4420902682 claims later ordinary extraction can truncate the same-report
weekly expiry. Existing observed_shift_expiry is already used by that writer.
Verify the exact reconciliation-first/ordinary-second order without production
changes; do not remove the established observation-expiry policy.

Verified RED at the reviewed commit: the split morning value left a daily expiry,
and both reasoning/text and tool_result/text containing valid shift JSON changed
native state to night (3 failed / 15 passed). The reconciliation-first ordering
test passed before repair: ordinary _persist_context_payload already delegates
to observed_shift_expiry, which retains the longer Friday endpoint.

The final boundary owns an answer-only assembler instead of the general display
normalizer: scalar/legacy text is retained, only type=text structured blocks
contribute text, and fragments concatenate without added or stripped characters.
The shared provider/display normalizer remains unchanged. Verification: 84
shift/provenance cases plus 320 context/reconciler cases passed (404 distinct),
with 18 new cases in this PR. Compile and diff checks pass. No new live data,
config, provider or runtime operation was performed during review repair.
