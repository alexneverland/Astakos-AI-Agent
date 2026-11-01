import pytest
from unittest.mock import patch, mock_open
from core.utils import extract_text_preview

def test_extract_text_preview_bounded():
    with patch("builtins.open", mock_open(read_data="a" * 100)) as mock_file:
        with patch("core.i18n.t", side_effect=lambda key, **kw: "...[clipped]" if key == "api.server.text_preview_clipped" else key):
            result = extract_text_preview("dummy.txt", 10)
            # Should have called read(11) precisely once
            mock_file().read.assert_called_once_with(11)
            # Result should be exactly max_chars long, containing marker
            # "...[clipped]" is 12 chars. So 10 < 12. So it should fallback to "aaaaaaaaaa"
            assert result == "aaaaaaaaaa"
            assert len(result) == 10

def test_extract_text_preview_clipped_normal():
    # max_chars=20, marker=12 chars, budget=8 chars
    with patch("builtins.open", mock_open(read_data="a" * 100)) as mock_file:
        with patch("core.i18n.t", side_effect=lambda key, **kw: "...[clipped]" if key == "api.server.text_preview_clipped" else key):
            result = extract_text_preview("dummy.txt", 20)
            mock_file().read.assert_called_once_with(21)
            assert result == "a" * 8 + "...[clipped]"
            assert len(result) == 20

def test_extract_text_preview_fits():
    with patch("builtins.open", mock_open(read_data="hello")) as mock_file:
        result = extract_text_preview("dummy.txt", 10)
        mock_file.assert_called_once_with(
            "dummy.txt",
            "r",
            encoding="utf-8",
            errors="ignore",
        )
        mock_file().read.assert_called_once_with(11)
        assert result == "hello"

def test_extract_text_preview_empty():
    with patch("builtins.open", mock_open(read_data="")) as mock_file:
        with patch("core.i18n.t", return_value="EMPTY"):
            result = extract_text_preview("dummy.txt", 10)
            assert result == "EMPTY"

def test_extract_text_preview_tiny_max_chars():
    with patch("builtins.open", mock_open(read_data="a" * 100)) as mock_file:
        with patch("core.i18n.t", side_effect=lambda key, **kw: "...[clipped]" if key == "api.server.text_preview_clipped" else key):
            # max_chars=5 is less than the marker length (12)
            result = extract_text_preview("dummy.txt", 5)
            assert result == "aaaaa"
            assert len(result) == 5

def test_extract_text_preview_zero_or_negative():
    assert extract_text_preview("dummy.txt", 0) == ""
    assert extract_text_preview("dummy.txt", -5) == ""

def test_extract_text_preview_failure():
    with patch("builtins.open", side_effect=OSError("Access denied")):
        with patch("core.i18n.t", side_effect=lambda key, **kw: "UNREADABLE" if key == "api.server.text_unreadable_generic" else key):
            with patch("logging.warning") as mock_warn:
                result = extract_text_preview("dummy.txt", 10)
                assert result == "UNREADABLE"
                mock_warn.assert_called_once()
                args, kwargs = mock_warn.call_args
                # Ensure no raw exception string is returned
                assert "Access denied" not in result
