"""
Tests για το ❤️ reaction handler.
Τρέξε: venv/Scripts/python.exe tests/test_reaction_handler.py
"""
import sys, os, threading, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from unittest.mock import patch, MagicMock

errors = []

def check(desc, cond, detail=""):
    if cond:
        print(f"✅ {desc}")
    else:
        msg = f"{desc}" + (f" — {detail}" if detail else "")
        errors.append(msg)
        print(f"❌ {msg}")


# ── Setup: mock TELEGRAM_CHAT_ID & TELEGRAM_TOKEN ──────────────────
import clients.telegram_bot as bot

FAKE_CHAT_ID = "999"
bot.TELEGRAM_CHAT_ID = FAKE_CHAT_ID


# ── 1. Cache: αποθηκεύει και επιστρέφει σωστά ─────────────────────
bot._bot_message_cache.clear()
bot._cache_bot_message(101, "Καλημέρα Μάστορα!")
bot._cache_bot_message(102, "Πώς μπορώ να βοηθήσω;")

with bot._bot_message_cache_lock:
    check("Cache: αποθηκεύει message_id 101", 101 in bot._bot_message_cache)
    check("Cache: αποθηκεύει message_id 102", 102 in bot._bot_message_cache)
    check("Cache: σωστό κείμενο για 101",
          bot._bot_message_cache.get(101) == "Καλημέρα Μάστορα!")


# ── 2. Cache: sliding window — max 50 entries ─────────────────────
bot._bot_message_cache.clear()
for i in range(55):
    bot._cache_bot_message(i, f"msg {i}")

with bot._bot_message_cache_lock:
    size = len(bot._bot_message_cache)
check("Cache: δεν ξεπερνά τα 50 entries", size <= bot._BOT_CACHE_MAX,
      f"size={size}")


# ── 3. _handle_message_reaction: αγνοεί άλλο chat_id ─────────────
bot._bot_message_cache.clear()
bot._cache_bot_message(200, "Τεστ μήνυμα")

saved_calls = []
with patch.object(bot.threading, "Thread") as mock_thread:
    bot._handle_message_reaction({
        "chat": {"id": "000"},  # άλλος χρήστης
        "message_id": 200,
        "new_reaction": [{"type": "emoji", "emoji": "❤️"}],
        "old_reaction": []
    })
    check("Reaction: αγνοεί μη εξουσιοδοτημένο chat", not mock_thread.called)


# ── 4. _handle_message_reaction: αγνοεί μη-❤️ reaction ───────────
bot._bot_message_cache.clear()
bot._cache_bot_message(201, "Τεστ μήνυμα 2")

with patch.object(bot.threading, "Thread") as mock_thread:
    bot._handle_message_reaction({
        "chat": {"id": FAKE_CHAT_ID},
        "message_id": 201,
        "new_reaction": [{"type": "emoji", "emoji": "👍"}],
        "old_reaction": []
    })
    check("Reaction: αγνοεί non-❤️ emoji", not mock_thread.called)


# ── 5. _handle_message_reaction: πιάνει ❤️ και βρίσκει κείμενο από cache ──
bot._bot_message_cache.clear()
bot._cache_bot_message(202, "Αυτό είναι σημαντικό!")

thread_started = threading.Event()
captured_text = []

original_thread = threading.Thread

class _FakeThread:
    def __init__(self, target=None, args=(), daemon=False, **kw):
        self._target = target
        self._args = args
    def start(self):
        if self._target:
            captured_text.append(self._args[0] if self._args else None)
            thread_started.set()

with patch("clients.telegram_bot.threading.Thread", _FakeThread), \
     patch("clients.telegram_bot.send_telegram_msg"):
    bot._handle_message_reaction({
        "chat": {"id": FAKE_CHAT_ID},
        "message_id": 202,
        "new_reaction": [{"type": "emoji", "emoji": "❤️"}],
        "old_reaction": []
    })

check("Reaction ❤️: εκκινεί background thread", thread_started.wait(timeout=2))
check("Reaction ❤️: περνά το σωστό κείμενο στο thread",
      captured_text and captured_text[0] == "Αυτό είναι σημαντικό!",
      str(captured_text))


# ── 6. _handle_message_reaction: fallback στο SQLite αν δεν υπάρχει στο cache ──
bot._bot_message_cache.clear()  # cache κενό

thread_started2 = threading.Event()
captured_text2 = []

class _FakeThread2:
    def __init__(self, target=None, args=(), daemon=False, **kw):
        self._target = target
        self._args = args
    def start(self):
        if self._target:
            captured_text2.append(self._args[0] if self._args else None)
            thread_started2.set()

mock_history = [
    {"role": "user", "content": "Ερώτηση χρήστη"},
    {"role": "assistant", "content": "Απάντηση από SQLite fallback"},
]

with patch("clients.telegram_bot.threading.Thread", _FakeThread2), \
     patch("clients.telegram_bot.send_telegram_msg"), \
     patch("memory.conversation_history.load_messages", return_value=mock_history):
    bot._handle_message_reaction({
        "chat": {"id": FAKE_CHAT_ID},
        "message_id": 999,  # δεν υπάρχει στο cache
        "new_reaction": [{"type": "emoji", "emoji": "❤️"}],
        "old_reaction": []
    })

check("Reaction ❤️: SQLite fallback εκκινεί thread", thread_started2.wait(timeout=2))
check("Reaction ❤️: SQLite fallback βρίσκει σωστό κείμενο",
      captured_text2 and captured_text2[0] == "Απάντηση από SQLite fallback",
      str(captured_text2))


# ── Αποτελέσματα ────────────────────────────────────────────────────
print()
if errors:
    print(f"❌ {len(errors)} αποτυχίες:")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
else:
    print("✅ Όλα τα tests πέρασαν!")
