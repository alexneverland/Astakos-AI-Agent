import re
from pathlib import Path


def test_api_server_never_returns_raw_exception_text():
    source = (
        Path(__file__).resolve().parents[1] / "api" / "server.py"
    ).read_text(encoding="utf-8")

    assert not re.search(
        r'["\'](?:error|message)["\']\s*:\s*str\(e\)',
        source,
    )
