# OwnTracks background GPS over Tailscale

Source feature, **not yet included in the published v2.8.0 image**. Element
remains the conversation app; OwnTracks supplies actual owner GPS fixes without
renewing Element's eight-hour live share. Astakos does not install a broker or
an OwnTracks Recorder, and does not retain a historical GPS track.

## Prerequisites

Complete the normal Setup Wizard first: select Matrix and configure the encrypted
owner room/device, then enter home coordinates and radius if home/leave reminders
are wanted. GPS alone never establishes partner/child presence or work status.
Both the Web/API and selected external worker must run from this source version
with the same project storage. Normal source supervisors handle code reload.

Tailscale must be connected on the phone and host. Use **Serve**, never public
Funnel. HTTPS and a separate 256-bit generated GPS credential protect this intake;
the existing Web token does not authorize it. No loopback/proxy bypass applies.

## Host provisioning

After reviewing/installing this source, run from the Astakos directory. Substitute
your own host's `.ts.net` name; do not include a password in the URL:

```powershell
.\venv\Scripts\python.exe scripts\configure_owntracks.py --url "https://YOUR-HOST.YOUR-TAILNET.ts.net/owntracks/"
```

The helper creates `credentials/owntracks-auth.json` (a verifier only) and
`credentials/owntracks.otrc` (private phone configuration including its credential).
Neither is versioned. A complete installation is preserved; rerunning does not
rotate or overwrite it. If setup stopped after creating only the phone import,
rerun with the same URL: a validated import restores its missing verifier using
the same token. Invalid partial imports are preserved and rejected.
Treat the `.otrc` as a password. Transfer it privately to your
phone, import it in OwnTracks, then remove unnecessary transferred copies.
These credentials are excluded from the data-only backup; preserve them separately
or reprovision and reimport on a replacement host. Restrict the credentials
directory to your Windows account/service account; POSIX writes use mode 0600.

The verifier hashes a machine-generated 256-bit token, not a human-chosen
password. The SHA-256 password-hashing CodeQL findings were reviewed on this
basis; this format must not be reused for human passwords.

Add only the dedicated mount, retaining Matrix's existing `/` handler:

```powershell
& 'C:\Program Files\Tailscale\tailscale.exe' serve --bg --https=443 --set-path=/owntracks/ http://127.0.0.1:8000/owntracks/
& 'C:\Program Files\Tailscale\tailscale.exe' serve status
```

Serve removes the external mount prefix and appends the remaining path to the
proxy target. This targets Astakos's dedicated `/owntracks/` subapplication,
which exposes only POST `/`, with no docs/admin endpoints. Do not proxy the entire
Astakos API at `/`: its normal trusted-local exemptions are unsuitable for a
general reverse proxy. Confirm `/` still points to Matrix port 8008 and only
`/owntracks/` points to the intake. No router port forwarding is needed.

## Android

Install OwnTracks, import the private `.otrc`, and confirm HTTP mode, authentication,
device ID `phone`, username `owner`, and your HTTPS URL. Permit precise location
**all the time**, notifications, background operation and automatic startup.
Exclude both OwnTracks and Tailscale from battery restrictions.

If importing reports "Message is not a valid configuration message", check the
received file size first. A zero-byte Taildrop file is incomplete: transfer the
original again under a new `.otrc` name, verify its size matches the host copy,
then import it from OwnTracks Configuration management. Do not disable HTTPS or
authentication to troubleshoot a file-import error.

The import requests Significant mode, an interval of 120 seconds, displacement 0,
balanced power, accuracy at most 100 metres and ping disabled. Displacement 0
permits updates while stationary; the interval is an Android request, not a timing
guarantee. Balanced power may provide insufficient accuracy indoors. Diagnose
actual fix age/accuracy before increasing power; Move mode consumes more battery.

Pings are intentionally ignored: OwnTracks can put a new timestamp on an old
coordinate. A heartbeat must not invent fresh whereabouts. Astakos accepts only
actual fixes no more than 10 minutes old, with a finite accuracy at most 100 metres.
Missing accuracy fails closed. Offline buffered old fixes, future timestamps,
duplicates and reordered points never refresh flags or fire location reminders.

## Verify and troubleshoot

Publish one actual location manually. OwnTracks should report HTTP success; this
means durable intake, **not reminder delivery**. Within the next five-second
external-worker tick, accepted fixes use the same location/context/reminder path
as Matrix. A pending location reminder is completed only through that path after
delivery. A failed transport leaves it pending for the next fresh actual fix.
The queue holds at most 100 points and one timestamp watermark, not a track archive.
Points are claimed before processing to avoid replaying uncertain interrupted
delivery; after interruption wait for a new fix rather than resending an old one.

Verify one update on mobile data with the screen locked and one while stationary;
confirm source timestamps advance. No automated Android test is claimed here.
If timestamps stop, the location becomes unknown under the existing freshness
policy; do not extend that policy to conceal a stopped phone client.

- `401`: missing/wrong dedicated Basic credential.
- `403`: wrong/missing `X-Limit-D` phone identifier.
- `422`: malformed coordinates/time/accuracy or JSON.
- `408` / `413`: request upload timeout (10 seconds) / body above 8 KiB.
- `503`: not provisioned, corrupt verifier, or intake storage unavailable.
- `200 []` without a new point: irrelevant message, ping, stale/inaccurate fix,
  or duplicate/out-of-order source timestamp. Coordinates and credentials are not
  logged. Confirm actual phone fix time and accuracy locally.

Removing the GPS Serve mount leaves Matrix operational:

```powershell
& 'C:\Program Files\Tailscale\tailscale.exe' serve --https=443 --set-path=/owntracks/ off
```

Stop OwnTracks sharing before rotating/reprovisioning credentials. Preserve the
queue watermark and existing location state; do not reset them as an upgrade step.

## Protocol references

[OwnTracks HTTP authentication and acknowledgements](https://owntracks.org/booklet/tech/http/),
[fix timestamps, ping semantics and configuration](https://owntracks.org/booklet/tech/json/),
[Android location modes and displacement](https://owntracks.org/booklet/features/location/),
[Android background restrictions](https://owntracks.org/booklet/features/android/),
[Tailscale Serve](https://tailscale.com/docs/reference/tailscale-cli/serve).
