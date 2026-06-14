from types import SimpleNamespace

from tools import georgian


class _FakeTranslateResponse:
    def __init__(self, translated: str):
        self._translated = translated

    def raise_for_status(self):
        return None

    def json(self):
        return [[[self._translated]]]


def test_detects_georgian_script():
    assert georgian._is_georgian("გამარჯობა")
    assert not georgian._is_georgian("καλημέρα")


def test_phonetic_transliterates_georgian_letters():
    assert georgian._to_phonetic("გამარჯობა") == "gamarjoba"


def test_translate_auto_greek_to_georgian(monkeypatch):
    calls = []

    def fake_get(url, params, timeout):
        calls.append(SimpleNamespace(url=url, params=params, timeout=timeout))
        return _FakeTranslateResponse("გამარჯობა")

    monkeypatch.setattr(georgian.requests, "get", fake_get)

    result = georgian.translate("καλημέρα")

    assert result["translated"] == "გამარჯობა"
    assert result["phonetic"] == "gamarjoba"
    assert result["src"] == "el"
    assert result["tgt"] == "ka"
    assert calls[0].params["sl"] == "el"
    assert calls[0].params["tl"] == "ka"


def test_translate_auto_georgian_to_greek(monkeypatch):
    def fake_get(url, params, timeout):
        assert params["sl"] == "ka"
        assert params["tl"] == "el"
        return _FakeTranslateResponse("γεια σου")

    monkeypatch.setattr(georgian.requests, "get", fake_get)

    result = georgian.translate("გამარჯობა")

    assert result["translated"] == "γεια σου"
    assert result["phonetic"] == ""
    assert result["src"] == "ka"
    assert result["tgt"] == "el"


def test_phrases_message_contains_short_command_tip():
    message = georgian.phrases_message()

    assert "Γρήγορες Φράσεις" in message
    assert "/g &lt;κείμενο&gt;" in message
