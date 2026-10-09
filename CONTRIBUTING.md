# Contributing to Astakos

Astakos is a local-first assistant maintained by Lazaros Avramidis
([alexneverland](https://github.com/alexneverland)). External contributors are
welcome to fork the repository and submit pull requests; write access is not
needed and is not granted automatically.

## Workflow

1. Fork the repository and create a short-lived branch from `main`.
2. Follow [AGENTS.md](AGENTS.md), preserve existing behavior, and keep the change
   focused. Describe the problem, scope, and verification in the PR.
3. Add regression coverage for behavioral changes and run the relevant offline
   tests with the project virtual environment:

   ```powershell
   .\venv\Scripts\python.exe -m pytest tests/test_relevant_module.py -q
   git diff --check
   ```

   Replace the example test path with the tests relevant to your change. On
   Linux/macOS use `./venv/bin/python`. See [SETUP_GUIDE.md](SETUP_GUIDE.md) for
   development setup.
4. Do not use live user data or contact cloud providers, Telegram, or Matrix in
   offline tests. Mock outbound boundaries and use isolated temporary storage.
5. Never commit credentials, environment secrets, live databases, crypto stores,
   uploads, or personal runtime state. Do not rewrite Git history as cleanup.
6. Address actionable review findings and resolve review conversations before
   merge. Automated review comments or reactions do not replace passing checks.

The maintainer merges PRs. The repository supports a solo-maintainer workflow
without requiring a second human approval; the protected `main` still requires
a PR, required checks, and resolved review conversations. Feature branches may
be deleted after merge. Squash, merge commits, and rebase remain supported.

## Documentation and releases

Update README/setup/discovery docs and the Unreleased changelog for user-visible
changes. Keep source `main` separate from published releases, and document any
explicit migration or activation requirement. Documentation-only edits need link,
command and whitespace review; do not rerun the full suite without a relevant reason.

Verify review findings against current code and fix actionable defects. Additional
automated review requests are owner-controlled; do not create an endless speculative
review cycle. Release preparation must keep `VERSION`, the dated changelog and
`SECURITY.md` consistent. Tag/image publication is a separate approved action;
see [release readiness](docs/release-readiness.md).

## Licensing and security

First-party contributions are submitted under the repository's
[MIT license](LICENSE). Preserve third-party copyright and license notices;
do not relabel vendored code as Astakos-owned or change its license. Identify
the source and license of newly included third-party material in your PR.

For vulnerabilities, follow [SECURITY.md](SECURITY.md) and use private reporting
instead of publishing exploit details or secrets in a public issue.
