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
