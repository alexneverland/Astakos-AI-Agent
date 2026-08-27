# ================================================================
# Project: Astakos AI Agent 🦞
# Module:  Tests for Audio Transcription Migration (PR 3A)
# Description: Offline deterministic tests for Telegram and Web audio transcription
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

import io
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from api.server import server, LOCAL_TOKEN
from core.ai_provider import (
    CapabilityNotSupportedError,
    ProviderAuthError,
    RateLimitError,
    GeminiAPIAdapter,
    VertexAIAdapter,
)
from tests.fixtures.provider_mocks import (
    MockOpenAIAdapter,
    MockGeminiAPIAdapter,
    MockVertexAIAdapter,
    MockAnthropicAdapter,
)


class TestTelegramVoiceHandlerMigration:
    """Validates Telegram handle_voice integration with AI provider adapters."""

    def test_telegram_handle_voice_vertex_success(self, monkeypatch):
        import clients.telegram_bot as bot
        import tools.telegram as telegram_tools

        mock_adapter = MockVertexAIAdapter()
        messages_sent = []
        handled_messages = []

        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: mock_adapter)
        monkeypatch.setattr(telegram_tools, "send_telegram_msg", lambda text: messages_sent.append(text))
        monkeypatch.setattr(bot, "handle_message", lambda text, chat_id: handled_messages.append((text, chat_id)))
        monkeypatch.setattr(bot, "_handle_transcribed_voice", lambda transcript: False)

        # Mock Telegram getFile and download
        mock_get_resp = MagicMock()
        mock_get_resp.json.return_value = {"result": {"file_path": "voice/test.ogg"}}
        mock_download_resp = MagicMock()
        mock_download_resp.content = b"fake_ogg_bytes"

        def mock_requests_get(url, **kwargs):
            if "getFile" in url:
                return mock_get_resp
            return mock_download_resp

        monkeypatch.setattr(bot.requests, "get", mock_requests_get)

        bot.handle_voice({"file_id": "voice_123"}, "chat_456")

        assert len(handled_messages) == 1
        msg_text, chat_id = handled_messages[0]
        assert chat_id == "chat_456"
        assert "[VOICE]: [VOICE_INPUT]" in msg_text
        assert "[Vertex Mock Audio]: Transcribed test voice" in msg_text

    def test_telegram_handle_voice_real_vertex_adapter_dedicated_transcribe(self, monkeypatch):
        import clients.telegram_bot as bot
        import tools.telegram as telegram_tools

        real_adapter = VertexAIAdapter(project_id="test-proj", location="europe-west1")
        mock_genai_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = "Στείλε μήνυμα στον Γιώργο"
        mock_genai_client.models.generate_content.return_value = mock_resp
        get_client_locations = []

        def _mock_get_client(location=None):
            get_client_locations.append(location)
            return mock_genai_client

        monkeypatch.setattr(real_adapter, "_get_genai_client", _mock_get_client)

        handled_messages = []
        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: real_adapter)
        monkeypatch.setattr(telegram_tools, "send_telegram_msg", lambda text: None)
        monkeypatch.setattr(bot, "handle_message", lambda text, chat_id: handled_messages.append((text, chat_id)))
        monkeypatch.setattr(bot, "_handle_transcribed_voice", lambda transcript: False)

        mock_get_resp = MagicMock()
        mock_get_resp.json.return_value = {"result": {"file_path": "voice/test.ogg"}}
        mock_download_resp = MagicMock()
        mock_download_resp.content = b"fake_ogg_bytes"
        monkeypatch.setattr(
            bot.requests,
            "get",
            lambda url, **kwargs: mock_get_resp if "getFile" in url else mock_download_resp,
        )

        bot.handle_voice({"file_id": "voice_123"}, "chat_456")

        assert len(handled_messages) == 1
        msg_text, chat_id = handled_messages[0]
        assert chat_id == "chat_456"
        assert "[VOICE]: [VOICE_INPUT] Στείλε μήνυμα στον Γιώργο" == msg_text

        # Verify dedicated client requested 'global' location while adapter preserves 'europe-west1'
        assert get_client_locations == ["global"]
        assert real_adapter.location == "europe-west1"

        call_kwargs = mock_genai_client.models.generate_content.call_args.kwargs
        assert call_kwargs["model"] == "gemini-3.5-transcribe-preview"
        assert call_kwargs["contents"] == [{"inline_data": {"mime_type": "audio/ogg", "data": b"fake_ogg_bytes"}}]
        assert call_kwargs.get("config") is None

    def test_telegram_handle_voice_real_vertex_adapter_silence_replies_politely(self, monkeypatch):
        import clients.telegram_bot as bot
        import tools.telegram as telegram_tools
        from core.i18n import t

        real_adapter = VertexAIAdapter(project_id="test-proj", location="europe-west1")
        mock_genai_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = ""
        mock_genai_client.models.generate_content.return_value = mock_resp
        monkeypatch.setattr(real_adapter, "_get_genai_client", lambda location=None: mock_genai_client)

        handled_messages = []
        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: real_adapter)
        monkeypatch.setattr(telegram_tools, "send_telegram_msg", lambda text: None)
        monkeypatch.setattr(bot, "handle_message", lambda text, chat_id: handled_messages.append((text, chat_id)))
        monkeypatch.setattr(bot, "_handle_transcribed_voice", lambda transcript: False)

        mock_get_resp = MagicMock()
        mock_get_resp.json.return_value = {"result": {"file_path": "voice/test.ogg"}}
        mock_download_resp = MagicMock()
        mock_download_resp.content = b"fake_ogg_bytes"
        monkeypatch.setattr(
            bot.requests,
            "get",
            lambda url, **kwargs: mock_get_resp if "getFile" in url else mock_download_resp,
        )

        bot.handle_voice({"file_id": "voice_123"}, "chat_456")

    def test_telegram_handle_voice_real_gemini_adapter_dedicated_transcribe(self, monkeypatch):
        import clients.telegram_bot as bot
        import tools.telegram as telegram_tools

        real_adapter = GeminiAPIAdapter(api_key="test-api-key")
        mock_genai_client = MagicMock()
        mock_file = MagicMock()
        mock_file.name = "files/test_ogg_file"
        mock_file.uri = "https://generativelanguage.googleapis.com/v1beta/files/test_ogg_file"
        mock_genai_client.files.upload.return_value = mock_file

        mock_interaction = MagicMock(output_text="Στείλε μήνυμα στον Γιώργο")
        mock_genai_client.interactions.create.return_value = mock_interaction
        monkeypatch.setattr(real_adapter, "_get_genai_client", lambda: mock_genai_client)

        handled_messages = []
        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: real_adapter)
        monkeypatch.setattr(telegram_tools, "send_telegram_msg", lambda text: None)
        monkeypatch.setattr(bot, "handle_message", lambda text, chat_id: handled_messages.append((text, chat_id)))
        monkeypatch.setattr(bot, "_handle_transcribed_voice", lambda transcript: False)

        mock_get_resp = MagicMock()
        mock_get_resp.json.return_value = {"result": {"file_path": "voice/test.ogg"}}
        mock_download_resp = MagicMock()
        mock_download_resp.content = b"fake_ogg_bytes"
        monkeypatch.setattr(
            bot.requests,
            "get",
            lambda url, **kwargs: mock_get_resp if "getFile" in url else mock_download_resp,
        )

        bot.handle_voice({"file_id": "voice_123"}, "chat_456")

        assert len(handled_messages) == 1
        msg_text, chat_id = handled_messages[0]
        assert chat_id == "chat_456"
        assert "[VOICE]: [VOICE_INPUT] Στείλε μήνυμα στον Γιώργο" == msg_text

        # Verify Files upload and Interactions create calls
        assert mock_genai_client.files.upload.call_args.kwargs["config"].mime_type == "audio/ogg"
        create_kwargs = mock_genai_client.interactions.create.call_args.kwargs
        assert create_kwargs["model"] == "gemini-3.5-transcribe"
        assert create_kwargs["generation_config"]["transcription_config"]["mode"]["type"] == "verbatim"
        mock_genai_client.files.delete.assert_called_once_with(name="files/test_ogg_file")

    def test_telegram_handle_voice_real_gemini_adapter_silence_replies_politely(self, monkeypatch):
        import clients.telegram_bot as bot
        import tools.telegram as telegram_tools
        from core.i18n import t

        real_adapter = GeminiAPIAdapter(api_key="test-api-key")
        mock_genai_client = MagicMock()
        mock_file = MagicMock()
        mock_file.name = "files/silent_ogg_file"
        mock_file.uri = "https://generativelanguage.googleapis.com/v1beta/files/silent_ogg_file"
        mock_genai_client.files.upload.return_value = mock_file

        mock_interaction = MagicMock(output_text="")
        mock_genai_client.interactions.create.return_value = mock_interaction
        monkeypatch.setattr(real_adapter, "_get_genai_client", lambda: mock_genai_client)

        handled_messages = []
        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: real_adapter)
        monkeypatch.setattr(telegram_tools, "send_telegram_msg", lambda text: None)
        monkeypatch.setattr(bot, "handle_message", lambda text, chat_id: handled_messages.append((text, chat_id)))
        monkeypatch.setattr(bot, "_handle_transcribed_voice", lambda transcript: False)

        mock_get_resp = MagicMock()
        mock_get_resp.json.return_value = {"result": {"file_path": "voice/test.ogg"}}
        mock_download_resp = MagicMock()
        mock_download_resp.content = b"fake_ogg_bytes"
        monkeypatch.setattr(
            bot.requests,
            "get",
            lambda url, **kwargs: mock_get_resp if "getFile" in url else mock_download_resp,
        )

        bot.handle_voice({"file_id": "voice_123"}, "chat_456")

        assert len(handled_messages) == 1
        msg_text, chat_id = handled_messages[0]
        assert t("clients.telegram_bot.bot_msg_dacaa2") in msg_text
        mock_genai_client.files.delete.assert_called_once_with(name="files/silent_ogg_file")

    def test_telegram_handle_voice_openai_success(self, monkeypatch):
        import clients.telegram_bot as bot
        import tools.telegram as telegram_tools

        mock_adapter = MockOpenAIAdapter()
        handled_messages = []

        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: mock_adapter)
        monkeypatch.setattr(telegram_tools, "send_telegram_msg", lambda text: None)
        monkeypatch.setattr(bot, "handle_message", lambda text, chat_id: handled_messages.append((text, chat_id)))
        monkeypatch.setattr(bot, "_handle_transcribed_voice", lambda transcript: False)

        mock_get_resp = MagicMock()
        mock_get_resp.json.return_value = {"result": {"file_path": "voice/test.ogg"}}
        mock_download_resp = MagicMock()
        mock_download_resp.content = b"fake_ogg_bytes"

        monkeypatch.setattr(
            bot.requests,
            "get",
            lambda url, **kwargs: mock_get_resp if "getFile" in url else mock_download_resp,
        )

        bot.handle_voice({"file_id": "voice_123"}, "chat_456")

        assert len(handled_messages) == 1
        assert "[OpenAI Mock Audio]: Transcribed test voice" in handled_messages[0][0]

    def test_telegram_handle_voice_anthropic_unsupported_notifies_user(self, monkeypatch):
        import clients.telegram_bot as bot
        import tools.telegram as telegram_tools

        mock_adapter = MockAnthropicAdapter()
        messages_sent = []
        handled_messages = []

        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: mock_adapter)
        monkeypatch.setattr(telegram_tools, "send_telegram_msg", lambda text: messages_sent.append(text))
        monkeypatch.setattr(bot, "handle_message", lambda text, chat_id: handled_messages.append((text, chat_id)))

        mock_get_resp = MagicMock()
        mock_get_resp.json.return_value = {"result": {"file_path": "voice/test.ogg"}}
        mock_download_resp = MagicMock()
        mock_download_resp.content = b"fake_ogg_bytes"

        monkeypatch.setattr(
            bot.requests,
            "get",
            lambda url, **kwargs: mock_get_resp if "getFile" in url else mock_download_resp,
        )

        bot.handle_voice({"file_id": "voice_123"}, "chat_456")

        # Handled message must NOT be called
        assert len(handled_messages) == 0
        # User must receive a clear capability warning message
        assert len(messages_sent) == 1
        assert "not supported by the active AI provider" in messages_sent[0]

    def test_telegram_handle_voice_auth_and_rate_limit_errors(self, monkeypatch):
        import clients.telegram_bot as bot
        import tools.telegram as telegram_tools

        mock_get_resp = MagicMock()
        mock_get_resp.json.return_value = {"result": {"file_path": "voice/test.ogg"}}
        mock_download_resp = MagicMock()
        mock_download_resp.content = b"fake_ogg_bytes"

        monkeypatch.setattr(
            bot.requests,
            "get",
            lambda url, **kwargs: mock_get_resp if "getFile" in url else mock_download_resp,
        )

        # 1. Auth error
        messages_auth = []
        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: MockVertexAIAdapter(should_fail_auth=True))
        monkeypatch.setattr(telegram_tools, "send_telegram_msg", lambda text: messages_auth.append(text))
        bot.handle_voice({"file_id": "voice_123"}, "chat_456")
        assert len(messages_auth) == 1
        assert "authentication failed" in messages_auth[0].lower()

        # 2. Rate limit error
        messages_quota = []
        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: MockVertexAIAdapter(should_rate_limit=True))
        monkeypatch.setattr(telegram_tools, "send_telegram_msg", lambda text: messages_quota.append(text))
        bot.handle_voice({"file_id": "voice_123"}, "chat_456")
        assert len(messages_quota) == 1
        assert "quota or rate limit exceeded" in messages_quota[0].lower()


class TestWebVoiceEndpointMigration:
    """Validates Web /voice endpoint integration with AI provider adapters."""

    @pytest.fixture
    def client(self):
        return TestClient(server)

    @property
    def auth_headers(self):
        return {"Authorization": f"Bearer {LOCAL_TOKEN}"}

    def test_web_voice_vertex_success(self, client, monkeypatch):
        mock_adapter = MockVertexAIAdapter()
        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: mock_adapter)

        response = client.post(
            "/voice",
            files={"file": ("test.webm", b"mock_webm_audio_bytes", "audio/webm")},
            headers=self.auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["transcription"] == "[Vertex Mock Audio]: Transcribed test voice"

    def test_web_voice_real_vertex_adapter_dedicated_transcribe(self, client, monkeypatch):
        real_adapter = VertexAIAdapter(project_id="test-proj", location="europe-west1")
        mock_genai_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = "Σημείωσε ραντεβού αύριο στις 10"
        mock_genai_client.models.generate_content.return_value = mock_resp
        get_client_locations = []

        def _mock_get_client(location=None):
            get_client_locations.append(location)
            return mock_genai_client

        monkeypatch.setattr(real_adapter, "_get_genai_client", _mock_get_client)
        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: real_adapter)

        response = client.post(
            "/voice",
            files={"file": ("test.webm", b"mock_webm_audio_bytes", "audio/webm")},
            headers=self.auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["transcription"] == "Σημείωσε ραντεβού αύριο στις 10"
        assert get_client_locations == ["global"]
        assert real_adapter.location == "europe-west1"

    def test_web_voice_real_vertex_adapter_silence_returns_no_audio_heard(self, client, monkeypatch):
        from core.i18n import t
        real_adapter = VertexAIAdapter(project_id="test-proj", location="europe-west1")
        mock_genai_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = ""
        mock_genai_client.models.generate_content.return_value = mock_resp
        monkeypatch.setattr(real_adapter, "_get_genai_client", lambda location=None: mock_genai_client)
        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: real_adapter)

        response = client.post(
            "/voice",
            files={"file": ("test.webm", b"silent_audio_bytes", "audio/webm")},
            headers=self.auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["error"] == t("api.server.no_audio_heard")

    def test_web_voice_real_gemini_adapter_dedicated_transcribe(self, client, monkeypatch):
        real_adapter = GeminiAPIAdapter(api_key="test-api-key")
        mock_genai_client = MagicMock()
        mock_file = MagicMock()
        mock_file.name = "files/test_webm_file"
        mock_file.uri = "https://generativelanguage.googleapis.com/v1beta/files/test_webm_file"
        mock_genai_client.files.upload.return_value = mock_file

        mock_interaction = MagicMock(output_text="Σημείωσε ραντεβού αύριο στις 10")
        mock_genai_client.interactions.create.return_value = mock_interaction
        monkeypatch.setattr(real_adapter, "_get_genai_client", lambda: mock_genai_client)
        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: real_adapter)

        response = client.post(
            "/voice",
            files={"file": ("test.webm", b"mock_webm_audio_bytes", "audio/webm")},
            headers=self.auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["transcription"] == "Σημείωσε ραντεβού αύριο στις 10"

        # Verify Files upload and Interactions create calls
        assert mock_genai_client.files.upload.call_args.kwargs["config"].mime_type == "audio/webm"
        create_kwargs = mock_genai_client.interactions.create.call_args.kwargs
        assert create_kwargs["model"] == "gemini-3.5-transcribe"
        assert create_kwargs["generation_config"]["transcription_config"]["mode"]["type"] == "verbatim"
        mock_genai_client.files.delete.assert_called_once_with(name="files/test_webm_file")

    def test_web_voice_real_gemini_adapter_silence_returns_no_audio_heard(self, client, monkeypatch):
        from core.i18n import t
        real_adapter = GeminiAPIAdapter(api_key="test-api-key")
        mock_genai_client = MagicMock()
        mock_file = MagicMock()
        mock_file.name = "files/silent_webm_file"
        mock_file.uri = "https://generativelanguage.googleapis.com/v1beta/files/silent_webm_file"
        mock_genai_client.files.upload.return_value = mock_file

        mock_interaction = MagicMock(output_text="")
        mock_genai_client.interactions.create.return_value = mock_interaction
        monkeypatch.setattr(real_adapter, "_get_genai_client", lambda: mock_genai_client)
        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: real_adapter)

        response = client.post(
            "/voice",
            files={"file": ("test.webm", b"silent_audio_bytes", "audio/webm")},
            headers=self.auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["error"] == t("api.server.no_audio_heard")
        mock_genai_client.files.delete.assert_called_once_with(name="files/silent_webm_file")

    def test_web_voice_openai_success(self, client, monkeypatch):
        mock_adapter = MockOpenAIAdapter()
        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: mock_adapter)

        response = client.post(
            "/voice",
            files={"file": ("test.webm", b"mock_webm_audio_bytes", "audio/webm")},
            headers=self.auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["transcription"] == "[OpenAI Mock Audio]: Transcribed test voice"

    def test_web_voice_anthropic_unsupported_returns_400(self, client, monkeypatch):
        mock_adapter = MockAnthropicAdapter()
        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: mock_adapter)

        response = client.post(
            "/voice",
            files={"file": ("test.webm", b"mock_webm_audio_bytes", "audio/webm")},
            headers=self.auth_headers,
        )

        assert response.status_code == 400
        data = response.json()
        assert "Voice input is not supported for active provider 'anthropic'" in data["error"]

    def test_web_voice_auth_and_rate_limit_status_codes(self, client, monkeypatch):
        # 401 Auth Failure
        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: MockGeminiAPIAdapter(should_fail_auth=True))
        resp_auth = client.post(
            "/voice",
            files={"file": ("test.webm", b"mock_webm_audio_bytes", "audio/webm")},
            headers=self.auth_headers,
        )
        assert resp_auth.status_code == 401
        assert "Voice transcription authentication failed for provider 'gemini'" in resp_auth.json()["error"]
        assert "Mock provider authentication failure" not in resp_auth.json()["error"]

        # 429 Quota / Rate Limit Failure
        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: MockGeminiAPIAdapter(should_rate_limit=True))
        resp_quota = client.post(
            "/voice",
            files={"file": ("test.webm", b"mock_webm_audio_bytes", "audio/webm")},
            headers=self.auth_headers,
        )
        assert resp_quota.status_code == 429
        assert "Quota or rate limit exceeded for provider 'gemini'" in resp_quota.json()["error"]

    def test_web_voice_silence_returns_user_friendly_error(self, client, monkeypatch):
        mock_adapter = MagicMock()
        mock_adapter.transcribe_audio.return_value = "[SILENCE]"
        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: mock_adapter)

        response = client.post(
            "/voice",
            files={"file": ("test.webm", b"silent_audio_bytes", "audio/webm")},
            headers=self.auth_headers,
        )

        assert response.status_code == 200
        assert "error" in response.json()
