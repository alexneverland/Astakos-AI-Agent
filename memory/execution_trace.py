# ================================================================
# Project: Astakos AI Agent 🦞
# Module:  Execution Trace — Per-turn agent/tool call recorder
#
# Γράφει ένα JSON trace ανά συνομιλία:
#   logs/traces/YYYY-MM-DD.json
#
# Κάθε trace περιέχει:
#   - user_message, channel, timestamp
#   - agent που χειρίστηκε
#   - κάθε tool call: name, args (preview), result (preview), duration_ms
#   - final response (preview)
#   - error / loop_guard αν υπάρχει
# ================================================================

import os
import json
import time
import uuid
import threading
from datetime import datetime

_TRACES_DIR = os.path.join(os.path.dirname(__file__), "..", "logs", "traces")
_write_lock = threading.Lock()

_MAX_STR = 300   # max chars για args/result preview
_MAX_MSG = 200   # max chars για user/response preview


def _truncate(val, maxlen: int = _MAX_STR) -> str:
    s = str(val) if not isinstance(val, str) else val
    return s[:maxlen] + ("…" if len(s) > maxlen else "")


class ExecutionTrace:
    """
    Δημιουργείται στην αρχή κάθε graph.stream() call.
    Συλλέγει δεδομένα ενώ τρέχει το stream.
    Αποθηκεύεται με .save() στο τέλος.

    Χρήση:
        trace = ExecutionTrace(channel="telegram", user_message="...")
        for event in graph.stream(...):
            trace.process_event(event)
        trace.finalize(response="...", error=None)
        trace.save()
    """

    def __init__(self, channel: str, user_message: str):
        self.trace_id       = str(uuid.uuid4())[:8]
        self.start_ts       = time.monotonic()
        self.timestamp      = datetime.now().isoformat(timespec="seconds")
        self.channel        = channel
        self.user_message   = _truncate(user_message, _MAX_MSG)
        self.agent          = None          # τελευταίος agent node
        self.tool_calls     = []            # list of dicts
        self.response       = None          # final response preview
        self.error          = None
        self.loop_guard     = False
        self._pending: dict = {}            # tool_call_id → {name, args, t0}

    # ── Stream event processor ───────────────────────────────────

    def process_event(self, event: dict):
        """Καλείται για κάθε event του graph.stream()."""
        for node, data in event.items():
            if node == "tool_loop_block":
                self.loop_guard = True
            if data is None:
                continue
            msgs = data.get("messages", [])
            for msg in msgs:
                self._process_message(node, msg)
            # Agent node → αποθήκευσε όνομα
            if node not in ("supervisor", "tools", "__end__"):
                self.agent = node

    def _process_message(self, node: str, msg):
        # AIMessage με tool_calls → pending calls
        tool_calls = getattr(msg, "tool_calls", None)
        if tool_calls:
            for tc in tool_calls:
                tid  = tc.get("id") or tc.get("tool_call_id") or str(uuid.uuid4())[:8]
                name = tc.get("name", "unknown")
                args = tc.get("args", {})
                self._pending[tid] = {
                    "tool":       name,
                    "args":       _truncate(json.dumps(args, ensure_ascii=False)),
                    "t0":         time.monotonic(),
                }

        # ToolMessage → match με pending και record result
        if getattr(msg, "type", None) == "tool" or msg.__class__.__name__ == "ToolMessage":
            tid     = getattr(msg, "tool_call_id", None)
            name    = getattr(msg, "name", None)
            content = getattr(msg, "content", "")
            pending = self._pending.pop(tid, None) if tid else None

            duration_ms = int((time.monotonic() - pending["t0"]) * 1000) if pending else None
            tool_name   = (pending or {}).get("tool") or name or "unknown"
            args_prev   = (pending or {}).get("args", "—")

            result_str  = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)

            # Detect loop guard στο result
            if "Tool loop stopped" in result_str or "Repeated tool call" in result_str:
                self.loop_guard = True

            self.tool_calls.append({
                "tool":        tool_name,
                "args":        args_prev,
                "result":      _truncate(result_str),
                "duration_ms": duration_ms,
                "error":       result_str.startswith("❌") or "Error" in result_str[:80],
            })

    # ── Finalize & Save ──────────────────────────────────────────

    def finalize(self, response: str | None = None, error: str | None = None):
        """Κλείνει το trace με final response και error."""
        if response:
            self.response = _truncate(response, _MAX_MSG)
            if "Tool loop stopped" in response or "Repeated tool call" in response or "επαναλαμβανόμενες κλήσεις εργαλείων" in response:
                self.loop_guard = True
        if error:
            self.error = _truncate(str(error), 200)
        self.duration_ms = int((time.monotonic() - self.start_ts) * 1000)

    def save(self):
        """Αποθηκεύει στο logs/traces/YYYY-MM-DD.json (thread-safe append)."""
        try:
            os.makedirs(_TRACES_DIR, exist_ok=True)
            today     = datetime.now().strftime("%Y-%m-%d")
            log_file  = os.path.join(_TRACES_DIR, f"{today}.json")
            tmp_file  = log_file + ".tmp"

            record = {
                "trace_id":    self.trace_id,
                "timestamp":   self.timestamp,
                "channel":     self.channel,
                "agent":       self.agent,
                "user_message": self.user_message,
                "tool_calls":  self.tool_calls,
                "response":    self.response,
                "loop_guard":  self.loop_guard,
                "error":       self.error,
                "duration_ms": getattr(self, "duration_ms", None),
            }

            with _write_lock:
                entries = []
                if os.path.exists(log_file):
                    try:
                        with open(log_file, "r", encoding="utf-8") as f:
                            entries = json.load(f)
                    except Exception:
                        entries = []
                entries.append(record)
                with open(tmp_file, "w", encoding="utf-8") as f:
                    json.dump(entries, f, ensure_ascii=False, indent=2)
                    f.flush(); os.fsync(f.fileno())
                os.replace(tmp_file, log_file)

        except Exception as e:
            print(f"\033[93m[ExecutionTrace]: Σφάλμα αποθήκευσης: {e}\033[0m")


# ── Convenience: read today's traces ────────────────────────────

def load_traces(date: str | None = None, limit: int = 50) -> list:
    """Διαβάζει traces ημέρας (default: σήμερα). Επιστρέφει τα τελευταία N."""
    day      = date or datetime.now().strftime("%Y-%m