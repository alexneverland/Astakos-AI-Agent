import json
from datetime import datetime

import memory.vector_store as vector_store


def test_audit_log_uses_atomic_json_append(monkeypatch, tmp_path):
    monkeypatch.setattr(vector_store, "MEMORY_AUDIT_DIR", str(tmp_path))

    vector_store._audit_log("add", category="family", fact="one")
    vector_store._audit_log("overwrite", category="family", fact="two")

    today = datetime.now().strftime("%Y-%m-%d")
    log_file = tmp_path / f"{today}.json"
    assert log_file.exists()

    data = json.loads(log_file.read_text(encoding="utf-8"))
    assert [entry["op"] for entry in data] == ["add", "overwrite"]
    assert not list(tmp_path.glob("*.tmp"))
