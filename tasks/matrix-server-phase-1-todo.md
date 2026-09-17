# Tasks: Private Matrix Server, Phase 1

- [x] Inventory Neverland and identify conflicts.
  - Acceptance: Docker works; host resources, relevant ports, existing Compose
    files, and Tailscale availability are known.
  - Verify: read-only PowerShell inventory.

- [x] Enroll Neverland in Tailscale and select the permanent server name.
  - Acceptance: Tailscale is installed, connected, and the MagicDNS hostname is
    confirmed by the user before Synapse configuration is generated.
  - Verify: `tailscale status --json` with only local non-secret fields shown.

- [x] Create the isolated Synapse/PostgreSQL runtime.
  - Acceptance: Compose validates; PostgreSQL has no published host port;
    registration and federation are disabled; secrets stay outside Git.
  - Verify: rendered Compose/config checks before `up -d`.

- [x] Start and verify the homeserver locally.
  - Acceptance: both containers are healthy and Synapse responds on its health
    endpoint without affecting Astakos.
  - Verify: Compose status, container health, and localhost HTTP probe.

- [ ] Enable private HTTPS and complete the Element X smoke test.
  - Acceptance: a Tailscale-connected phone can log in and exchange one
    encrypted-room message with a manually created account.
  - Verify: HTTPS probe and manual Element X test.

- [ ] Document backup and recovery commands.
  - Acceptance: signing key, Synapse config, and PostgreSQL data have a clear,
    tested backup boundary without copying plaintext credentials into Git.
  - Verify: dry-run file inventory and documented restore prerequisites.
