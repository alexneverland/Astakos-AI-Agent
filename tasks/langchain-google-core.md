# Coordinated LangChain Google/Core update

Baseline: main 90c4e50002143770eef099fb22cbc6355a52390c, 2026-11-02.

The proposed Google integration 4.4.2 requires langchain-core>=1.6.10. Update
these two pins together, selecting the minimum required Core release. Preserve
the tested LangGraph 1.2 range and all application routing, tool selection,
draft persistence, provenance and external-action approval logic.

Acceptance criteria:
- Complete requirements resolve and install in an isolated Windows/Python 3.14
  environment, and resolve on Linux/Python 3.11.
- Provider/voice/embeddings and native tool schema boundaries work offline.
- Graph, Messenger preparation/send and approval regressions pass with native
  temporary stores, with outbound transport blocked.
- No live provider calls, data/config changes, supervisor changes or releases.

This slice is independent of protobuf/TTS and Python-baseline/NumPy upgrades.
Tests must also cover the final combined installed set before claiming local
completion. Publication is a PR, not implicit permission to merge this new slice.

Verified: complete clean Windows/Python 3.14 installation passes dependency
checks. 184 focused provider/voice/embeddings, tool/approval and Messenger cases
pass. Linux/Python 3.11 full-manifest resolver verification is captured separately.
The local coordinated two-package install also passes pip check with protobuf 7
and the upgraded Cloud TTS package present.
