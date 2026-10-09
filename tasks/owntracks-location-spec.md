# OwnTracks location intake

Owner approved implementation on 2026-10-09 after reviewing HTTP intake over
the existing Tailscale network. One capability: background owner GPS without
Element's eight-hour sharing renewal. No public Funnel or MQTT infrastructure.

## Contract and boundaries

- `POST /owntracks/` accepts OwnTracks HTTP JSON and returns `200 []` after
  durable intake, not after reminder delivery. Dedicated generated 256-bit
  Basic credential, stored as a SHA-256 verifier under ignored `credentials/`;
  mandatory even for loopback/proxy callers. Configured device header required.
  Existing Web token and auth exemptions never authorize this route.
- Limit bodies to 8 KiB, reject malformed coordinates, timestamps and accuracy.
  Accept only fresh actual fixes (maximum age 600 seconds, no future timestamps,
  accuracy at most 100 metres). Drop ping reports: OwnTracks may refresh their
  timestamp while reusing old coordinates. Acknowledge irrelevant/stale reports
  without state changes, so they do not block the phone's offline queue.
- Bounded durable queue (100 points), monotonic source timestamp deduplication,
  five-second selected external worker drain. No cloud/model calls. Use the
  canonical location pipeline and confirmed selected-channel reminder delivery.
  Validate freshness again at consumption; serialize location processing across
  transports. GPS updates owner whereabouts only, not work/family presence.
- Retain only bounded pending points and a timestamp watermark; no track archive,
  coordinates or credentials in logs. Credentials/export are excluded from the
  data-only backup and require separate private backup/reprovisioning.
- Reuse automatic source supervisors. No .env/config.py, database migrations,
  Docker/watchdog changes or live credential writes in this implementation.
  Tailscale and phone activation follow review, with exact commands documented.

## Implementation plan / task list

1. Add offline HTTP abuse-case and durable intake tests; verify RED.
2. Implement dedicated auth, bounded parser/queue and API mount; verify GREEN.
3. Extend canonical source-time handling and selected-worker drain; verify real
   temporary persistence, reminders, failed transport, stale/reordered fixes.
4. Add opt-in provisioning CLI and documented phone/Tailscale configuration;
   run focused regressions, compilation and `git diff --check`, inspect diff.

Existing tasks/plan.md and tasks/todo.md contain historical observation work;
this narrow feature's ordered tasks are kept here without overwriting them.

## Commands and verification

Python >=3.11, existing FastAPI, filelock and pytest; no new dependencies.
Use typed Python functions and docstrings, e.g.
`def parse_location(payload: dict, *, now_ts: float) -> dict | None:`.

`venv\Scripts\python.exe -m pytest tests/test_owntracks.py -q --basetemp=.pytest_tmp_owntracks`

Regression scope: Matrix location/runtime, shared scheduler, API authentication,
location reminders. Offline transports fail loudly; stores are temporary.
Phone/Android timing and battery behavior require separate real-device validation;
backend tests do not prove mobile delivery. No Android interaction tests authored.

## Sources

- https://owntracks.org/booklet/tech/http/
- https://owntracks.org/booklet/tech/json/
- https://owntracks.org/booklet/features/location/
- https://tailscale.com/docs/reference/tailscale-cli/serve

OwnTracks pings explicitly substitute a current timestamp. Android significant
mode combines interval and displacement; use interval 120 seconds, displacement
0, ping disabled initially. OS power management can still delay real fixes.

## Verification recorded 2026-10-09

- Final focused PR check (OwnTracks, scheduler startup, API authentication,
  Matrix runtime and existing home/work environmental context): 81 passed,
  one existing dependency warning.

- Implemented intake, provisioning, worker composition, shared source-time
  handling and documentation; 30 new OwnTracks tests pass (final HTTP rerun).
- Combined location/scheduler/API/Matrix runtime/reminder run: 121 passed,
  three failures. All three reproduced with HEAD's original location module
  loaded in memory: legacy Matrix-vs-Telegram transport assumption, outdated
  same-value GPS refresh expectation, and Windows temp SQLite cleanup lock.
  No failures hidden or tests disabled; no unrelated repairs bundled.
- In-memory mutation removing ping rejection made the ping regression fail.
  No production source or live location was mutated for this experiment.
- Python compilation and diff checks pass. Subsequent authorized host/phone
  activation is recorded below; no release is part of this task.
- Owner's 18:17:26 departure follow-up was traced to real Matrix GPS at 18:15:24
  (474 metres after 164-minute stay). Owner confirmed stepping into the yard;
  test GPS never overwrote live coordinates.

## Host activation

Owner subsequently explicitly authorized Tailscale/host activation. Provisioned
the GPS-only credential and private phone import locally; restricted both files'
Windows ACLs to owner/SYSTEM/Administrators. Added persistent tailnet-only Serve
`/owntracks/` -> `http://127.0.0.1:8000/owntracks/`, preserving Matrix root -> 8008.
Live HTTPS non-location probes passed: 401 unauthenticated, 403 wrong device,
200 [] valid authentication, 404 admin subpath, 200 Matrix versions. No synthetic
GPS writes. The first Taildrop copy was zero bytes on the phone; a second transfer
as owntracks-fixed.otrc completed and import succeeded. A real OwnTracks fix at
18:55:48 local time was durably accepted, consumed and persisted with the same
source timestamp. Continuous screen-off delivery remains to observe.

Existing home and work coordinates are both configured, with radii 150m and
300m respectively. The existing environmental context compares GPS against both;
this intake reuses canonical GPS storage. No reverse geocoding, named-region
intake or new work/family flag inference is included.
