import requests

from core.i18n import t
from tools.web import search_supermarket_prices


def test_supermarket_search_matches_fresh_chicken_tokens_in_any_order(monkeypatch):
    payload = {
        "context": {
            "MAPP_PRODUCTS": {
                "result": {
                    "merchants": [
                        {"merchant_uuid": "masoutis", "display_name": "Μασούτης"},
                    ],
                    "products": [
                        {
                            "name": "KNORR NOODLES ΚΟΤΟΠΟΥΛΟ 11/70G",
                            "prices": [{"merchant_uuid": "masoutis", "price": 0.62}],
                        },
                        {
                            "name": "ΚΟΤΟΠΟΥΛΟ ΝΩΠΟΤΑΤΟ(ΤΙΜ. ΚΙΛ)",
                            "prices": [{"merchant_uuid": "masoutis", "price": 1.99}],
                        },
                        {
                            "name": "ΠΙΝΔΟΣ ΚΟΤΟΠΟΥΛΟ ΕΛΛΗΝΙΚΟ ΝΩΠΟ(ΤΙΜ. ΚΙΛ)",
                            "prices": [{"merchant_uuid": "masoutis", "price": 2.99}],
                        },
                    ],
                },
            },
        },
    }

    class FakeResponse:
        def json(self):
            return payload

    monkeypatch.setattr(
        requests,
        "get",
        lambda url, timeout: FakeResponse(),
    )

    result = search_supermarket_prices.invoke({"query": "νωπό κοτόπουλο"})

    assert "ΠΙΝΔΟΣ ΚΟΤΟΠΟΥΛΟ ΕΛΛΗΝΙΚΟ ΝΩΠΟ" in result
    assert "Μασούτης: 2.99€" in result
    assert "KNORR NOODLES" not in result
    assert "ΝΩΠΟΤΑΤΟ" not in result


def test_supermarket_search_rejects_empty_query_without_fetching(monkeypatch):
    monkeypatch.setattr(
        requests,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("empty query must not fetch all products")
        ),
    )

    result = search_supermarket_prices.invoke({"query": ""})

    assert result == t("tools.web.ekat_not_found", query="")
