# Known places and execution evidence

## Named owner locations

`manage_known_places` is the canonical Home Agent tool for remembering a named
current location, listing locations, and matching a fresh fix against saved radii.
The registry includes home/work directly from their existing configuration;
custom locations live in private `known_places.json`. Home/work cannot be
overwritten through this tool. The cold data backup includes the custom registry.

An explicit request to save a current place uses `save_current`. Its coordinates
come from the canonical GPS file at execution, with a source time no more than
10 minutes old. Assistant prose, inferred coordinates, future timestamps and
stale fixes cannot substitute for a fresh fix. The default custom radius is
100 metres; a requested radius must be between 25 and 2,000 metres. Up to 100
custom places are stored. Re-saving the same exact name (case-insensitive) updates
that record. Names do not become paths or commands.

Saving is confirmed only when the tool returns `status=saved`. An ordinary
profile fact about a location does not create geometry in this registry. Existing
profile notes are not silently imported or replayed. A damaged registry is
preserved and produces an error, rather than being replaced by an empty store.

`list` returns configured and custom locations. `locate` compares fresh GPS to
their radii and reports matching names/distances. No match is an unknown place;
it does not establish a street address. Multiple matching radii remain visible.
GPS and known-place matches do not establish family presence, employment status
or route intention. Maps/geocoding behavior is a separate capability.

## Related context updates

Ordinary context extraction keeps trusted owner source IDs, observation times
and atomic state guards. A newer same-value observation preserves its own time
while independently supported relationship changes can still be committed.
Contrary newer evidence, changed expiry, invalid sources and newer owner reports
continue to prevent an older interpretation from overwriting current state.
Assistant acknowledgements are not proof that a flag was written.

## Matrix, Web and Telegram traces

### End-to-end latency

Text conversation handlers collect latency from entry through return, including
pre-graph routine/context processing, graph execution and post-graph response
work. The native trace uses that start time and is saved at handler exit, even
for early intercepts and errors. `duration_ms` is handler wall time; it excludes
transport work before handler dispatch and delivery after handler return. Matrix
delivery is outside its turn service; it is not included in that duration.

`latency` contains `total_ms`, `model_wall_ms`, `retry_wait_wall_ms`,
`uncovered_ms`, `spans` and `dropped_spans`. Each span records its start offset,
duration, stage and exception class when applicable. Model callbacks identify
provider, configured model, call ID and the nested stage path; native adapter
operations identify provider and operation. Spans never retain prompts, output,
credentials or exception messages. Existing bounded trace previews are separate.
Collection is capped at 512 spans per turn; `dropped_spans` makes truncation
explicit. Closed contexts ignore late background work and are isolated across
concurrent requests and worker threads.

Model and backoff totals use the union of their intervals: nested/concurrent
durations must not be added. `uncovered_ms` is wall time outside every recorded
span, not time outside model calls, and is not a diagnosis of its cause.
Application retries record each attempt and actual backoff duration. Model-call
duration includes opaque provider SDK retries, connection setup and network wait;
only retries exposed by callbacks are counted separately. It cannot separate
Google server processing from network delay or reveal private model reasoning.

The debug latency panel shows the totals and expandable timing spans. Terminal
`[LatencyTrace]:` JSON lines share the native trace ID, with start/end events for
stages and model calls. `model_started` identifies an ongoing call before it
finishes. `latency_finished` is the authoritative handler-end timing; the native
`turn_finished` graph/response event may precede post-graph delivery work.
To investigate a slow reply, find its trace ID, compare pre-graph spans, model
calls and backoffs, and inspect long named stages or uncovered time. Historical
traces lack these spans; their missing intervals cannot be reconstructed.

### Agent/tool evidence

Matrix graph turns use the shared ExecutionTrace recorder. Day files in
`logs/traces/YYYY-MM-DD.json` include channel, agent, tool argument/result previews,
durations, model phase timings, final response preview and errors. Matrix event ID
is the correlation ID, and `owner_rowid` links ordinary turns to persisted owner
history. `graph_used=0` distinguishes an intercepted command/context/draft response
from graph execution. Failed calls without a recorded result are `unresolved`;
they are not proof that an external operation failed or succeeded.

The shared recorder also mirrors turn evidence to the terminal with flushed
`[MatrixTrace]:`, `[WebTrace]:` or `[TelegramTrace]:`
JSON lines: `turn_started`, `phase`, `graph_step`, `tool_called`, `tool_result`,
`tool_unresolved` and `turn_finished`. Each line carries the channel, trace ID,
correlation ID and elapsed milliseconds, so interleaved turns can be followed.
Matrix uses its event ID; Web and Telegram use the trace ID when no external
correlation ID is supplied. Logging is on by default for these channels;
offline callers can explicitly pass `console=False` to retain only stored traces.
Tool arguments/results and final replies use the same bounded, credential-redacted
previews as the stored traces. A failed terminal write does not interrupt a turn.
Web and Telegram graph traces finalize and save from cleanup on success,
exceptions and empty replies (`NoResponse`). Telegram records stream events as
they arrive, so a later exception retains earlier pending tool calls. Awaiting
approval is an intercepted, completed trace; it is not an executed tool call.
Telegram photo traces remain open through archive-prompt preparation, output
extraction and sending; downstream failures are recorded at the final cleanup.
These lines appear in each worker's console/container output; the durable
record remains the shared day trace file. They describe observable execution,
not private model reasoning or transport delivery confirmation.

The existing `/debug/traces` view can read both channels. Thread and process locks
serialize Web/Matrix appends to the same day file. Credential-shaped fields and
bearer tokens are redacted before previews are truncated.
Credential fields include private keys and passphrases; complete or interrupted
PEM private-key blocks are also hidden. Text field values are scanned without
backtracking, including quoted multiline values, before the preview limit applies.
Previews are bounded local diagnostic data, not full transcripts or retroactive
traces for old turns.
Background context/memory queues have separate evidence; a graph trace does not
claim to record their full lifecycle. A generated response also does not prove
Matrix transport delivery: check the actual recorded external message receipt.
