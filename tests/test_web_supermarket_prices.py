import requests

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
