# Messenger structured decision repair

## Problem and contract

A mixed conversational request can produce draft-like prose without calling
the native draft writer. A subsequent send then finds no active draft. A routine
acknowledgement establishes engagement, not a saved draft or external delivery.

Both semantic Messenger decision resolvers formerly parsed str(response.content),
which does not extract a JSON answer from structured provider text blocks. The
required-native-write safeguard depends on the preparation decision, so losing
it permits prose-only synthesis. Provider-shaped fixtures reproduce this defect;
they do not establish the format of an unretained historical model response.

Use LangChain's answer-only AIMessage.text extraction for both semantic resolvers.
Preserve scalar/string fragments and typed text blocks, concatenated without
injected characters. Reasoning/tool/unknown blocks cannot supply permission.
Owner provenance, active-draft/contact eligibility, history/CAS guards, required
native persistence and revision-bound external approval remain unchanged.
No phrase lists, shared parser changes or new outbound behavior.

## Synthetic reproduction and validation

All new fixtures use an invented Demo contact, fake recipient, fictional routine
identity/date and a generic meeting message. A prior terminal draft and a routine
acknowledgement precede the mixed request. The model first supplies prose, then
returns a native draft tool call only when required. A later synthetic send request
must create exactly one approval bound to the new revision, without transport.
No personal transcript, relationship/location history or real contact identifier
is needed to reproduce the lifecycle.

At the original implementation, block/split preparation decisions left the old
revision unchanged while scalar preparation worked. Native graph readback after
repair verifies a pending draft containing the displayed message. Web-to-Matrix
approvals may be queued rather than synchronously notified; either route retains
the pending revision until approval. Malformed values, non-answer valid JSON and
untrusted owner messages confer no permission.

Initial verification covered 180 distinct relevant offline cases: 138 Messenger
cases including 18 new cases, plus 42 approval/routing/history/cross-process cases.
Compilation and git diff --check passed; two existing dependency warnings remain.
Offline fixtures verify persistence/approval behavior, not live semantic quality.
No full suite or live-model test was performed. Separately authorized operational
recovery is not a regression fixture; private details belong in runtime records,
not this source-controlled task document.

## Review repair and publication scope

The completed Codex review found no code issues. Sourcery identified personal
details in fixtures/task notes and two missing test-model method docstrings.
Owner authorized anonymization, documentation fixes, scoped commit/push and
final merge/deletion after checks. Production behavior remains unchanged by this
review repair. PR metadata is generalized too. Existing published history is not
rewritten; squash merge ensures the integration commit contains synthetic data.

Commands: venv/Scripts/python.exe -m pytest tests/test_messenger_structured_decisions.py
tests/test_messenger_lifecycle_regression.py -q --basetemp=.pytest_tmp_messenger_anonymized;
git diff --check. Use native temporary stores and blocked outbound transport.
Preserve real data, credentials/config/runtime and unrelated work;
no additional live send is required.

Review follow-up verification: all 54 affected synthetic-decision and lifecycle cases passed; compilation and git diff --check passed. Production code did not change in this follow-up.
