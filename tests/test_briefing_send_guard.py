from unittest.mock import mock_open, patch

import clients.telegram_bot as telegram_bot


def test_morning_ai_briefing_does_not_write_flag_when_send_fails():
    with patch("clients.telegram_bot.datetime") as dt_mock, \
         patch("clients.telegram_bot.os.path.exists", return_value=False), \
         patch("clients.telegram_bot._send_and_record_assistant", return_value=None), \
         patch("builtins.open", mock_open()) as open_mock, \
         patch("astakos_skills.morning_briefing.get_morning_briefing", return_value="briefing"):
        now_mock = dt_mock.now.return_value
        now_mock.hour = 8
        now_mock.strftime.return_value = "2026-07-17"

        telegram_bot.job_morning_ai_briefing()

    open_mock.assert_not_called()
