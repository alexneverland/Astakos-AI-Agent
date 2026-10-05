# OfficeCLI vendor binary

This folder is reserved for the third-party OfficeCLI binary used by Astakos through
`astakos_skills/officecli_skill.py`.

- Upstream: https://github.com/iOfficeAI/OfficeCLI
- Website: https://officecli.ai/
- License: Apache-2.0, see upstream `LICENSE`, `NOTICE`, and `THIRD-PARTY-NOTICES.txt`.

## Verified Windows release

- Release: [v1.0.154](https://github.com/iOfficeAI/OfficeCLI/releases/tag/v1.0.154)
- Source commit: `d49beb48af7c7f50c4ec745269ac4b5b44c866dc`
- Asset: `officecli-win-x64.exe` (33,497,000 bytes)
- SHA-256: `50a57626ff7c5b11034c23368312cdafbd436cf81eb149c81dc488e027a56e7e`
- Verified locally: 2026-10-05; replaces version 1.0.132.

The three notice/license files in this directory are unmodified copies from
that upstream tag. Astakos's own license is unchanged.

The local executable `officecli.exe` is intentionally ignored by git via:

```gitignore
vendor/officecli/*.exe
```

Download or update the binary from the official upstream release/source and place it here as:

```text
vendor/officecli/officecli.exe
```

Download the version-pinned Windows x64 asset, compare its SHA-256 with the
value above and the official release digest before executing it, then check
`officecli.exe --version`. A Git checkout does **not** install or upgrade this
ignored binary. Do not run upstream `install`, `skills` or `mcp` commands as
part of this update.

## Integration verification

The actual 1.0.154 binary created and edited temporary `.docx`, `.xlsx` and
`.pptx` fixtures; OpenXML validation returned zero errors for each. Fixtures
included Greek paragraph/title text and an Excel numeric cell. No real user
outputs were opened or changed; visual Office rendering was not tested.

Eleven offline adapter tests cover output-card tags for all three formats,
quoted filenames, rejection of shell operators and missing binaries:

```powershell
.\venv\Scripts\python.exe -m pytest --noconftest tests/test_officecli_adapter.py -q
```

These tests replace the subprocess boundary and do not execute the binary or
contact providers. Native smoke checks use `OFFICECLI_SKIP_UPDATE=1` and
`OFFICECLI_NO_AUTO_RESIDENT=1` in the checking process only. Upstream normally
checks for automatic updates; no user-level auto-update configuration or
application environment was changed, so the running version can later drift.

Before replacing an installed binary, keep its previous copy outside the
repository. To roll back, replace `officecli.exe` with that copy and verify
`--version`; reverting Git alone cannot roll back the ignored executable.

