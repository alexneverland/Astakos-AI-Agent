from unittest.mock import MagicMock, patch

from services.context_extractor import extract_and_update_context_flags


def test_context_extractor_uses_llm_relationship_state_without_phrase_overrides():
    with (
        patch("services.context_extractor.safe_gemini_call") as mock_llm,
        patch("services.context_extractor.get_context_state", return_value=None),
        patch("services.context_extractor.set_context_states_if_unchanged", return_value=True) as mock_set,
        patch("services.context_extractor.infer_routine_reconciliation_directives") as mock_reconcile,
        patch("services.context_extractor.apply_routine_reconciliation_directives"),
    ):
        mock_reconcile.return_value = []
        mock_llm.return_value = MagicMock(
            text='{"partner_with_user": true, "kid1_with_user": true}'
        )

        extract_and_update_context_flags("Είμαστε μαζί τώρα.")

    calls = {key: value for key, (value, _) in mock_set.call_args.args[0].items()}
    assert calls["partner_with_user"] == "true"
    assert calls["kid1_with_user"] == "true"
    assert calls["kid1_with_partner"] == "true"
    assert calls["kid1_away_from_home"] == "false"


def test_context_extractor_work_state_overrides_only_incompatible_relationships():
    with (
        patch("services.context_extractor.safe_gemini_call") as mock_llm,
        patch("services.context_extractor.get_context_state", return_value=None),
        patch("services.context_extractor.set_context_states_if_unchanged", return_value=True) as mock_set,
        patch("services.context_extractor.infer_routine_reconciliation_directives") as mock_reconcile,
        patch("services.context_extractor.apply_routine_reconciliation_directives"),
    ):
        mock_reconcile.return_value = []
        mock_llm.return_value = MagicMock(
            text=(
                '{"user_at_work": true, "partner_with_user": true, '
                '"kid1_with_user": true, "kid1_with_partner": true}'
            )
        )

        extract_and_update_context_flags("Είμαι στη δουλειά τώρα.")

    calls = {key: value for key, (value, _) in mock_set.call_args.args[0].items()}
    assert calls["user_at_work"] == "true"
    assert calls["partner_with_user"] == "false"
    assert calls["kid1_with_user"] == "false"
    assert calls["kid1_with_partner"] == "true"


def test_mixed_morning_message_sets_partner_not_working_as_together_at_home():
    with (
        patch("services.context_extractor.safe_gemini_call") as mock_llm,
        patch("services.context_extractor.get_context_state", return_value=None),
        patch("services.context_extractor.set_context_states_if_unchanged", return_value=True) as mock_set,
        patch("services.context_extractor.infer_routine_reconciliation_directives") as mock_reconcile,
        patch("services.context_extractor.apply_routine_reconciliation_directives"),
    ):
        mock_reconcile.return_value = []
        mock_llm.return_value = MagicMock(
            text=(
                '{"user_out_of_home": false, "kid1_away_from_home": true, '
                '"kid1_absence_scope": "temporary", "partner_at_work": false}'
            )
        )

        extract_and_update_context_flags(
            "καλημερα φιλε καθαρισα το κουνελι ο αλεξανδροσ ειναι σχολειο και εγω σπιτι καφεδακι η σοφια δεν δουλευει σημερα"
        )

    calls = {key: value for key, (value, _) in mock_set.call_args.args[0].items()}
    assert calls["user_out_of_home"] == "false"
    assert calls["kid1_away_from_home"] == "true"
    assert calls["partner_at_work"] == "false"
    assert calls["partner_with_user"] == "true"


def test_partner_not_at_work_while_user_out_of_home_sets_partner_with_user_false():
    with (
        patch("services.context_extractor.safe_gemini_call") as mock_llm,
        patch("services.context_extractor.get_context_state", return_value=None),
        patch("services.context_extractor.set_context_states_if_unchanged", return_value=True) as mock_set,
        patch("services.context_extractor.infer_routine_reconciliation_directives") as mock_reconcile,
        patch("services.context_extractor.apply_routine_reconciliation_directives"),
    ):
        mock_reconcile.return_value = []
        mock_llm.return_value = MagicMock(
            text='{"user_out_of_home": true, "partner_at_work": false}'
        )

        extract_and_update_context_flags("Είμαι έξω, η Σοφία δεν δουλεύει σήμερα.")

    calls = {key: value for key, (value, _) in mock_set.call_args.args[0].items()}
    assert calls["user_out_of_home"] == "true"
    assert calls["partner_at_work"] == "false"
    assert calls["partner_with_user"] == "false"
