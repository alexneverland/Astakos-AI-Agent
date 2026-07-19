from pathlib import Path


def test_legacy_pypdf2_dependency_is_not_used():
    root = Path(__file__).resolve().parents[1]
    requirements = (root / "requirements.txt").read_text(encoding="utf-8")
    source = (root / "tools" / "system.py").read_text(encoding="utf-8")

    assert "PyPDF2" not in requirements
    assert "from PyPDF2 import PdfReader" not in source
    assert "from pypdf import PdfReader" in source
