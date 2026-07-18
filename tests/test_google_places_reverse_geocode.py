from unittest.mock import MagicMock, patch

from tools.web import search_google_places


def _empty_places_response():
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"places": []}
    return response


def test_empty_query_with_coordinates_uses_nearby_distance_search(monkeypatch):
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "test-key")

    with patch("requests.post", return_value=_empty_places_response()) as post:
        search_google_places.func(
            query="",
            location="40.646621,22.936779",
        )

    url = post.call_args.args[0]
    payload = post.call_args.kwargs["json"]

    assert url.endswith(":searchNearby")
    assert payload["rankPreference"] == "DISTANCE"
    assert payload["locationRestriction"]["circle"]["radius"] == 50.0


def test_named_place_query_with_coordinates_keeps_text_search(monkeypatch):
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "test-key")

    with patch("requests.post", return_value=_empty_places_response()) as post:
        search_google_places.func(
            query="park",
            location="40.646621,22.936779",
        )

    url = post.call_args.args[0]
    payload = post.call_args.kwargs["json"]

    assert url.endswith(":searchText")
    assert payload["textQuery"] == "park"
    assert "locationBias" in payload


def test_empty_query_with_malformed_coordinates_falls_back_to_text_search(monkeypatch):
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "test-key")

    with patch("requests.post", return_value=_empty_places_response()) as post:
        search_google_places.func(
            query="",
            location="40.646621,22.936779,extra",
        )

    url = post.call_args.args[0]
    payload = post.call_args.kwargs["json"]

    assert url.endswith(":searchText")
    assert payload["textQuery"] == " 40.646621,22.936779,extra"
