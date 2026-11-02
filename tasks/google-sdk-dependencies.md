# Coordinated Google SDK dependency upgrade

Baseline: main 90c4e50002143770eef099fb22cbc6355a52390c, 2026-11-02.
User approved working through the previously blocked dependency updates in
separate slices after merging the three compatible proposals.

## Scope and acceptance criteria

- Upgrade protobuf to 7.36.2 together with Cloud Text-to-Speech 2.38.0.
- Prove complete fresh-install resolution on Windows/Python 3.14 and the
  supported Linux/Python 3.11 baseline, and exercise actual Google message
  serialization with synthetic data. Never call a live cloud service.
- Preserve all current providers, tool/approval boundaries, and embedded Chroma.
  No live data, credentials, configuration, runtime, image publication or releases.
- Verify the provider, voice, embeddings, graph/approval, and setup contracts
  offline with temporary native stores. Require pip check to pass.

## Installed-environment migration

The local-only packages google-generativeai 0.8.6 and its pinned dependency
google-ai-generativelanguage 0.6.15 are absent from the project manifest and have
no application imports. The first has no installed reverse dependents; the
second is required only by the first. Their obsolete protobuf<6 constraint is
the reason the standalone protobuf proposal could not update the old venv.
Archive the exact installed package inventory and prove an isolated candidate
before removing only these two legacy packages from the owner environment.
Do not remove other Google packages to silence a dependency conflict.

## Verification checklist

- [x] Confirm source imports and installed reverse dependencies.
- [x] Verify a clean candidate environment and Linux resolver.
- [x] Run real protobuf/Cloud TTS serialization without outbound transport.
- [x] Run focused application regressions before and after the change.
- [x] Inspect scoped diff and publish a reviewable PR; do not merge it implicitly.

The LangChain core/integration update and Python-baseline/NumPy update are
separate slices. Existing historical task specifications remain unchanged.

Evidence: fresh Windows/Python 3.14 candidate installs 184 compatible packages;
89 provider/voice/native-codec cases and 179 graph/approval/setup cases pass.
Four new real-codec cases also pass on the old environment. Full fresh
Linux/Python 3.11 requirements resolution succeeds. Local installation removes
only the two verified obsolete SDKs; their exact wheels and the baseline package
inventory are retained outside the repository for rollback.

Review follow-up: add four default-gRPC cases that retain the production client
factory, gRPC transport, interceptors and SDK-selected binary codecs, replacing
only channel I/O. Greek/English success and PERMISSION_DENIED paths pass. The
19 codec/API/voice cases pass on Windows; all eight codec cases also pass inside
the combined Linux/Python 3.12 image with network disabled. A temporary wrong
audio-encoding mutation is rejected by all four gRPC cases, then fully restored.
