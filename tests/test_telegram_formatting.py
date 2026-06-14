from tools.telegram import _plain_telegram_fallback, format_for_telegram


def test_format_for_telegram_preserves_bold_and_escapes_stray_angle_bracket():
    text = "<b>Ποτό με Αλόη</b>\nΣχεδόν μηδενική ζάχαρη (<0,5g ανά 100ml)."

    result = format_for_telegram(text)

    assert "<b>Ποτό με Αλόη</b>" in result
    assert "&lt;0,5g ανά 100ml" in result
    assert "(<0,5g" not in result


def test_format_for_telegram_converts_markdown_after_escaping_html():
    text = "**Βαθμολογία:** 5/10\n- κάτω από <1g ζάχαρη"

    result = format_for_telegram(text)

    assert "<b>Βαθμολογία:</b> 5/10" in result
    assert "• κάτω από &lt;1g ζάχαρη" in result


def test_plain_fallback_removes_telegram_tags():
    result = _plain_telegram_fallback("<b>Τίτλος</b> &lt;0,5g")

    assert result == "Τίτλος <0,5g"
