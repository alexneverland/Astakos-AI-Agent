from unittest.mock import MagicMock, patch

from services.context_extractor import extract_and_update_context_flags


def test_context_extractor_uses_llm_relationship_state_without_phrase_overrides():
    with (
        patch("services.context_extractor.safe_gemini_call") as mock_llm,
        patch("services.context_extractor.set_context_state") as mock_set,
        patch("services.context_extractor.reconcile_fact_to_routines") as mock_reconcile,
        patch("services.context_extractor.apply_routine_reconciliation_directives"),
    ):
        mock_reconcile.return_value = {"scored_directives": []}
        mock_llm.return_value = MagicMock(
            text='{"partner_with_user": true, "kid1_with_user": true}'
        )

        extract_and_update_context_flags("Είμαστε μαζί τώρα.")

    calls = {call.args[0]: call.args[1] for call in mock_set.call_args_list}
    assert calls["partner_with_user"] == "true"
    assert calls["kid1_with_user"] == "true"
    assert calls["kid1_with_partner"] == "true"
    assert calls["kid1_away_from_home"] == "false"


def test_context_extractor_work_state_overrides_only_incompatible_relationships():
    with (
        patch("services.context_extractor.safe_gemini_call") as mock_llm,
        patch("services.context_extractor.set_context_state") as mock_set,
        patch("services.context_extractor.reconcile_fact_to_routines") as mock_reconcile,
        patch("services.context_extractor.apply_routine_reconciliation_directives"),
    ):
        mock_reconcile.return_value = {"scored_directives": []}
        mock_llm.return_value = MagicMock(
            text=(
                '{"user_at_work": true, "partner_with_user": true, '
                '"kid1_with_user": true, "kid1_with_partner": true}'
            )
        )

        extract_and_update_context_flags("Είμαι στη δουλειά τώρα.")

    calls = {call.args[0]: call.args[1] for call in mock_set.call_args_list}
    assert calls["user_at_work"] == "true"
    assert calls["partner_with_user"] == "false"
    assert calls["kid1_with_user"] == "false"
    assert calls["kid1_with_partner"] == "true"
