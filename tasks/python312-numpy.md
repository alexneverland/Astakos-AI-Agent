# Python 3.12 baseline and NumPy 2.5.4

Baseline: main 90c4e50002143770eef099fb22cbc6355a52390c, 2026-11-02.
User approved addressing the blocked NumPy proposal through a supported newer
Docker Python baseline. Choose 3.12, the smallest baseline satisfying NumPy 2.5.

Scope: change only the Python image line in source/release Dockerfiles, NumPy
pin, current minimum-version documentation, and compatibility evidence. No
compose changes, live containers, runtime supervisors, data or image publication.

Acceptance criteria:
- Both Dockerfiles use the same Python 3.12 Trixie baseline; published old
  releases are not described as updated.
- A full AMD64 release-image build and offline API/native dependency smoke
  succeed. Test synthetic Chroma persistence and numerical/dataframe operations.
- Existing source/Office/refresh contracts and affected offline application
  tests pass. The installed Windows environment remains dependency-consistent.
- Explicitly report architecture/build limits; no release or tag is created.

This is independent of the Google SDK and LangChain/Core PRs; additionally check
the complete combined installed dependency set before declaring local completion.

Verification: full Linux/AMD64 Dockerfile.release build succeeds on Python
3.12.16. With network disabled, the API imports successfully; real NumPy/pandas
operations and ONNX Runtime native imports pass, and a fresh synthetic Chroma
store survives a writer-process exit and answers a reader-process vector query.
All four release entrypoint tests pass in the built image, including fresh and
existing synthetic workspace preservation. Windows candidate checks pass 69
vector-store, Office and source/release cases (the same 41 vector cases pass on
the previous NumPy). Four container cases are then run explicitly rather than
counting the earlier unconfigured skips as coverage.

The official base manifest provides AMD64 and ARM64 images. This task builds and
runs AMD64 only; it does not claim an executed ARM64 build or published image.
