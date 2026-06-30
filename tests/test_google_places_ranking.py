from tools.web import _build_places_query_profile, _score_place_match


def _place(name: str, ptype: str, rating: float, votes: int, review: str = "", **flags):
    return {
        "displayName": {"text": name},
        "primaryTypeDisplayName": {"text": ptype},
        "rating": rating,
        "userRatingCount": votes,
        "formattedAddress": "Νέα Καλλικράτεια",
        "reviews": [{"text": {"text": review}}] if review else [],
        "takeout": flags.get("takeout", False),
        "delivery": flags.get("delivery", False),
        "dineIn": flags.get("dineIn", True),
    }


def test_places_profile_detects_seafood_intent():
    profile = _build_places_query_profile("βρες μου 3 καλές ψαροταβέρνες κοντά στη Νέα Καλλικράτεια")
    assert "seafood" in profile["wanted"]


def test_seafood_place_scores_higher_than_generic_restaurant():
    profile = _build_places_query_profile("βρες μου καλές ψαροταβέρνες")
    seafood = _place(
        "Τα Δελφίνια",
        "Εστιατόριο",
        4.5,
        400,
        review="Φρέσκα ψάρια και ωραία θαλασσινά δίπλα στη θάλασσα",
    )
    generic = _place(
        "Burger House",
        "Εστιατόριο",
        4.7,
        700,
        review="Πολύ καλό burger και γρήγορο σέρβις",
    )
    assert _score_place_match(seafood, profile) > _score_place_match(generic, profile)


def test_delivery_intent_prefers_delivery_capable_place():
    profile = _build_places_query_profile("βρες μου καφέ με delivery")
    with_delivery = _place(
        "Coffee Spot",
        "Cafe",
        4.3,
        180,
        review="Ωραίος καφές",
        delivery=True,
    )
    without_delivery = _place(
        "Coffee Spot 2",
        "Cafe",
        4.4,
        220,
        review="Ωραίος καφές",
        delivery=False,
    )
    assert _score_place_match(with_delivery, profile) > _score_place_match(without_delivery, profile)
