# OfficeCLI vendor binary

This folder is reserved for the third-party OfficeCLI binary used by Astakos through
`astakos_skills/officecli_skill.py`.

- Upstream: https://github.com/iOfficeAI/OfficeCLI
- Website: https://officecli.ai/
- License: Apache-2.0, see upstream `LICENSE`, `NOTICE`, and `THIRD-PARTY-NOTICES.txt`.

## Pinned native provisioning

- Release: [v1.0.154](https://github.com/iOfficeAI/OfficeCLI/releases/tag/v1.0.154)
- Source commit: `d49beb48af7c7f50c4ec745269ac4b5b44c866dc`
- Asset: `officecli-win-x64.exe` (33,497,000 bytes)
- SHA-256: `50a57626ff7c5b11034c23368312cdafbd436cf81eb149c81dc488e027a56e7e`
- Verified locally: 2026-10-05; replaces version 1.0.132.

The three notice/license files in this directory are unmodified copies from
that upstream tag. Astakos's own license is unchanged.

Run the explicit installer from the repository root using your configured Python:

```powershell
python scripts/install_officecli.py
```

It selects the official v1.0.154 Windows/Linux/macOS x64 or ARM64 asset and checks
its exact size and SHA-256 against the pinned metadata in
[officecli_installation.py](../../services/officecli_installation.py). Verified
existing binaries are reused; failed downloads leave the old binary intact.
Canonical paths are `vendor/officecli/officecli.exe` on Windows and
`vendor/officecli/officecli` elsewhere. Both are ignored by Git. Do not run
upstream `install`, `skills` or `mcp` as part of Astakos provisioning.

Docker uses Debian Trixie with ICU and provisions the Linux executable during
build. `/opt/astakos-tools/officecli` supplies the native fallback when source
Compose mounts a checkout over `/app`. Wizard status and execution selection check
the pinned size and SHA-256 for the current platform. An invalid local executable
cannot run; Linux can select the verified bundled fallback instead. Manual Linux needs ICU; musl/Alpine is not
covered. Mac/ARM64 asset selection is tested, but native execution on all those
platforms has not been verified. A checkout alone does not install a binary.

## Integration verification

The Windows and Linux AMD64 1.0.154 binaries created and edited temporary `.docx`, `.xlsx` and
`.pptx` fixtures; OpenXML validation returned zero errors for each. Fixtures
included Greek paragraph/title text and an Excel numeric cell. No real user
outputs were opened or changed; visual Office rendering was not tested.

Thirteen offline adapter tests cover output-card tags for all three formats,
quoted filenames, rejection of shell operators and missing or unverified binaries:

```powershell
.\venv\Scripts\python.exe -m pytest --noconftest tests/test_officecli_adapter.py -q
```

These tests replace the subprocess boundary and do not execute the binary or
contact providers. Native smoke checks use `OFFICECLI_SKIP_UPDATE=1` and
`OFFICECLI_NO_AUTO_RESIDENT=1` in the checking process only. Upstream normally
checks for automatic updates; no user-level auto-update configuration or
application environment was changed. A binary changed by an upstream update must
match Astakos's pinned metadata before it can be selected again; rerun the pinned
installer to restore the accepted version.

Before replacing an installed binary, keep its previous copy outside the
repository. To roll back, replace `officecli.exe` with that copy and verify
`--version`; reverting Git alone cannot roll back the ignored executable.

