# OfficeCLI vendor binary

This folder is reserved for the third-party OfficeCLI binary used by Astakos through
`astakos_skills/officecli_skill.py`.

- Upstream: https://github.com/iOfficeAI/OfficeCLI
- Website: https://officecli.ai/
- License: Apache-2.0, see upstream `LICENSE`, `NOTICE`, and `THIRD-PARTY-NOTICES.txt`.

The local executable `officecli.exe` is intentionally ignored by git via:

```gitignore
vendor/officecli/*.exe
```

Download or update the binary from the official upstream release/source and place it here as:

```text
vendor/officecli/officecli.exe
```

