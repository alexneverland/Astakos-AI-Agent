# Spec: Private Matrix Server, Phase 1

## Objective

Run a private Matrix homeserver on the Neverland computer so the user can sign
in from Element X over the private Tailscale network. This phase establishes
the server only; Astakos message synchronization is a later, separate slice.

## Tech Stack

- Synapse homeserver in Docker
- PostgreSQL in the same private Compose network
- Tailscale for private reachability and HTTPS
- Windows 11 host with Docker Desktop Linux containers

## Commands

- Validate Compose: `docker compose --env-file <runtime-env> config --quiet`
- Start services: `docker compose --env-file <runtime-env> up -d`
- Check services: `docker compose --env-file <runtime-env> ps`
- Check Synapse: `docker compose --env-file <runtime-env> exec synapse python -m synapse.app.homeserver --help`

## Project Structure

- `C:\Neverland-Matrix\compose.yaml`: private Synapse and PostgreSQL services
- `C:\Neverland-Matrix\synapse\`: generated Synapse configuration and signing key
- `C:\Neverland-Matrix\postgres\`: Docker-managed database volume only
- `C:\Neverland-Matrix\.env`: runtime-only secrets, never committed or printed

## Configuration Style

```yaml
services:
  synapse:
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
```

Use explicit image versions, internal-only database networking, conservative
defaults, and comments only where a security boundary is not obvious.

## Testing Strategy

- Validate the rendered Compose model before starting containers.
- Verify PostgreSQL is not published on a host port.
- Verify Synapse registration and federation are disabled.
- Verify the homeserver health endpoint locally, then through Tailscale HTTPS.
- Perform one Element X login and one encrypted-room message smoke test after
  the user account is created.

## Boundaries

- Always: keep secrets outside Git, bind services privately, use manual account
  creation, and preserve the existing Astakos Docker setup.
- Ask first: choose or change the permanent Matrix `server_name`, create user
  credentials, expose a public port, enable federation, or add the Astakos
  Matrix adapter.
- Never: enable public registration, publish PostgreSQL, reuse Astakos secrets,
  edit `.env`/`config.py`, or modify Astakos databases.

## Success Criteria

- Synapse and PostgreSQL are healthy in their own Compose project.
- No Matrix or PostgreSQL service is publicly reachable from the LAN/Internet.
- The homeserver is reachable from a Tailscale-connected phone using HTTPS.
- Public registration and federation are disabled.
- Element X can log in with a manually created account.

## Open Questions

- The permanent `server_name` is selected after Tailscale enrollment reveals
  the Neverland MagicDNS name.
- Account names and passwords are intentionally deferred until the server is
  healthy.
