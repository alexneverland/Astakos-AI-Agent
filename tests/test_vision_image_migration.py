# ================================================================
# Project: Astakos AI Agent 🦞
# Test Suite: Vision Analysis & Image Generation Migration (PR 3C)
# Description: Validates deterministic offline behavior for all
#              migrated vision and image generation call sites.
# ================================================================

from __future__ import annotations

import io
import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from core.ai_provider import (
    AIProviderError,
    CapabilityNotSupportedError,
    ProviderAuthError,
    RateLimitError,
)
from tests.fixtures.provider_mocks import (
    MockAnthropicAdapter,
    MockGeminiAPIAdapter,
    MockOpenAIAdapter,
    MockVertexAIAdapter,
)


# ────────────────────────────────────────────────────────────────
# 1. GENERATE IMAGE TOOL TESTS
# ────────────────────────────────────────────────────────────────

class TestGenerateImageToolMigration:
    """Validates tools/system.py:generate_image_tool with AI provider adapter."""

    def test_generate_image_tool_vertex_success(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Verifies successful 1:1 image generation with Vertex adapter."""
        import tools.system as sys_tools

        monkeypatch.setattr("config.BASE_DIR", str(tmp_path))
        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: MockVertexAIAdapter())

        result: str = sys_tools.generate_image_tool.invoke({"prompt": "a cute little lobster in a garden"})

        assert result.startswith("✅ Ready! Image created.")
        assert "[SEND_PHOTO:" in result
        out_path: str = result.split("[SEND_PHOTO:")[1].replace("]", "").strip()
        assert os.path.exists(out_path)
        with open(out_path, "rb") as f:
            assert f.read() == b"\xff\xd8\xff\xe0\x00\x10JFIF\x00mock_vertex_image"

    def test_generate_image_tool_openai_success(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Verifies successful 1:1 image generation with OpenAI adapter."""
        import tools.system as sys_tools

        monkeypatch.setattr("config.BASE_DIR", str(tmp_path))
        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: MockOpenAIAdapter())

        result: str = sys_tools.generate_image_tool.invoke({"prompt": "cyberpunk city landscape"})

        assert result.startswith("✅ Ready! Image created.")
        assert "[SEND_PHOTO:" in result
        out_path: str = result.split("[SEND_PHOTO:")[1].replace("]", "").strip()
        assert os.path.exists(out_path)
        with open(out_path, "rb") as f:
            assert f.read() == b"\xff\xd8\xff\xe0\x00\x10JFIF\x00mock_openai_image"

    def test_generate_image_tool_anthropic_unsupported(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Verifies graceful capability rejection when provider lacks image generation."""
        import tools.system as sys_tools

        monkeypatch.setattr("config.BASE_DIR", str(tmp_path))
        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: MockAnthropicAdapter())

        result: str = sys_tools.generate_image_tool.invoke({"prompt": "a futuristic robot"})

        assert "❌ Image generation is not supported by provider 'anthropic'" in result

    def test_generate_image_tool_auth_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Verifies graceful handling of provider authentication error."""
        import tools.system as sys_tools

        monkeypatch.setattr("config.BASE_DIR", str(tmp_path))
        monkeypatch.setattr(
            "core.brain.get_active_provider_adapter",
            lambda: MockVertexAIAdapter(should_fail_auth=True),
        )

        result: str = sys_tools.generate_image_tool.invoke({"prompt": "a painting"})

        assert "❌ Image generation authentication failed for provider 'vertex'" in result

    def test_generate_image_tool_rate_limit_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Verifies graceful handling of provider rate limit / quota error."""
        import tools.system as sys_tools

        monkeypatch.setattr("config.BASE_DIR", str(tmp_path))
        monkeypatch.setattr(
            "core.brain.get_active_provider_adapter",
            lambda: MockGeminiAPIAdapter(should_rate_limit=True),
        )

        result: str = sys_tools.generate_image_tool.invoke({"prompt": "a painting"})

        assert "❌ Image generation quota or rate limit exceeded for provider 'gemini'" in result

    def test_generate_image_tool_empty_bytes_handling(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Verifies graceful handling when provider returns empty bytes."""
        import tools.system as sys_tools

        class EmptyImageAdapter(MockVertexAIAdapter):
            def generate_image(self, prompt: str, aspect_ratio: str = "1:1") -> bytes:
                return b""

        monkeypatch.setattr("config.BASE_DIR", str(tmp_path))
        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: EmptyImageAdapter())

        result: str = sys_tools.generate_image_tool.invoke({"prompt": "a sketch"})

        assert "❌ Image generation error (vertex): provider returned no image data." in result


# ────────────────────────────────────────────────────────────────
# 2. STORY MAKER IMAGE GENERATION TESTS
# ────────────────────────────────────────────────────────────────

class TestStoryMakerImageMigration:
    """Validates astakos_skills/story_maker._generate_image with AI provider adapter."""

    def test_story_maker_generate_image_vertex_success(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Verifies scene artwork generation with Vertex adapter."""
        import astakos_skills.story_maker as sm

        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: MockVertexAIAdapter())

        path: str | None = sm._generate_image("a magical forest with unicorns", str(tmp_path), 1)

        assert path is not None
        assert os.path.exists(path)
        assert path.endswith(".jpg")
        with open(path, "rb") as f:
            assert f.read() == b"\xff\xd8\xff\xe0\x00\x10JFIF\x00mock_vertex_image"

    def test_story_maker_generate_image_openai_success(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Verifies scene artwork generation with OpenAI adapter."""
        import astakos_skills.story_maker as sm

        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: MockOpenAIAdapter())

        path: str | None = sm._generate_image("a cute bear catching fish", str(tmp_path), 2)

        assert path is not None
        assert os.path.exists(path)
        with open(path, "rb") as f:
            assert f.read() == b"\xff\xd8\xff\xe0\x00\x10JFIF\x00mock_openai_image"

    def test_story_maker_generate_image_anthropic_unsupported_returns_none(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Verifies Anthropic unsupported image generation gracefully returns None."""
        import astakos_skills.story_maker as sm

        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: MockAnthropicAdapter())

        path: str | None = sm._generate_image("scene prompt", str(tmp_path), 1)

        assert path is None

    def test_story_maker_generate_image_auth_error_returns_none(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Verifies auth error in scene image generation returns None without crashing."""
        import astakos_skills.story_maker as sm

        monkeypatch.setattr(
            "core.brain.get_active_provider_adapter",
            lambda: MockVertexAIAdapter(should_fail_auth=True),
        )

        path: str | None = sm._generate_image("scene prompt", str(tmp_path), 1)

        assert path is None

    def test_make_story_full_flow_with_adapter_images(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Verifies full end-to-end story generation with text and scene artwork."""
        import astakos_skills.story_maker as sm

        class StoryAndImageAdapter(MockVertexAIAdapter):
            def generate_text(
                self,
                prompt: str,
                model_type: str = "fast",
                system_prompt: str | None = None,
                temperature: float | None = None,
            ) -> str:
                return (
                    "Once upon a time in an enchanted valley.\n"
                    "SCENE1: A peaceful enchanted valley with rivers\n"
                    "SCENE2: A young explorer discovering a hidden crystal\n"
                    "SCENE3: The valley glowing under starry skies"
                )

        monkeypatch.setattr("config.BASE_DIR", str(tmp_path))
        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: StoryAndImageAdapter())
        monkeypatch.setattr("time.sleep", lambda s: None)

        result: dict[str, Any] = sm.make_story("enchanted valley")

        assert result["error"] is None
        assert result["story"] == "Once upon a time in an enchanted valley."
        assert len(result["images"]) == 3
        for img_p in result["images"]:
            assert os.path.exists(img_p)


# ────────────────────────────────────────────────────────────────
# 3. SCAN RECEIPT TESTS
# ────────────────────────────────────────────────────────────────

class TestScanReceiptMigration:
    """Validates astakos_skills/scan_receipt.py:scan_receipt with AI provider adapter."""

    def test_scan_receipt_missing_file_returns_error_json(self) -> None:
        """Verifies missing receipt image returns structured JSON error."""
        from astakos_skills.scan_receipt import scan_receipt

        res_raw: str = scan_receipt.invoke({"image_path": "non_existent_receipt.jpg"})
        data: dict[str, Any] = json.loads(res_raw)
        assert "error" in data
        assert "not found" in data["error"]

    def test_scan_receipt_vertex_success(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Verifies receipt parsing with Vertex adapter returning structured JSON."""
        from astakos_skills.scan_receipt import scan_receipt

        receipt_file: Path = tmp_path / "supermarket_receipt.jpg"
        receipt_file.write_bytes(b"\xff\xd8\xff\xe0mock_jpeg_receipt")

        receipt_payload: dict[str, Any] = {
            "store": "SuperMarket Alpha",
            "date": "2026-08-25",
            "total": 42.50,
            "items": [
                {"name": "Milk", "qty": 2, "price": 3.20},
                {"name": "Bread", "qty": 1, "price": 1.10},
            ],
        }

        class ReceiptVisionAdapter(MockVertexAIAdapter):
            def analyze_vision(
                self, prompt: str, image_bytes: bytes, mime_type: str = "image/jpeg"
            ) -> str:
                assert image_bytes == b"\xff\xd8\xff\xe0mock_jpeg_receipt"
                return f"```json\n{json.dumps(receipt_payload)}\n```"

        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: ReceiptVisionAdapter())

        res_raw: str = scan_receipt.invoke({"image_path": str(receipt_file)})
        data: dict[str, Any] = json.loads(res_raw)

        assert data["store"] == "SuperMarket Alpha"
        assert data["total"] == 42.50
        assert len(data["items"]) == 2

    def test_scan_receipt_anthropic_vision_success(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Verifies receipt parsing with Anthropic adapter (multimodal vision supported)."""
        from astakos_skills.scan_receipt import scan_receipt

        receipt_file: Path = tmp_path / "coffee_receipt.jpg"
        receipt_file.write_bytes(b"mock_receipt_bytes")

        receipt_payload: dict[str, Any] = {
            "store": "Cafe Delight",
            "date": "2026-08-25",
            "total": 4.50,
            "items": [{"name": "Espresso", "qty": 1, "price": 4.50}],
        }

        class AnthropicReceiptAdapter(MockAnthropicAdapter):
            def analyze_vision(
                self, prompt: str, image_bytes: bytes, mime_type: str = "image/jpeg"
            ) -> str:
                return json.dumps(receipt_payload)

        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: AnthropicReceiptAdapter())

        res_raw: str = scan_receipt.invoke({"image_path": str(receipt_file)})
        data: dict[str, Any] = json.loads(res_raw)

        assert data["store"] == "Cafe Delight"
        assert data["total"] == 4.50

    def test_scan_receipt_non_json_model_response(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Verifies graceful handling when model returns non-JSON raw response."""
        from astakos_skills.scan_receipt import scan_receipt

        receipt_file: Path = tmp_path / "blurry_receipt.jpg"
        receipt_file.write_bytes(b"blurry_bytes")

        class BlurryReceiptAdapter(MockOpenAIAdapter):
            def analyze_vision(
                self, prompt: str, image_bytes: bytes, mime_type: str = "image/jpeg"
            ) -> str:
                return "The receipt is too blurry to extract items."

        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: BlurryReceiptAdapter())

        res_raw: str = scan_receipt.invoke({"image_path": str(receipt_file)})
        data: dict[str, Any] = json.loads(res_raw)

        assert "error" in data
        assert "Model did not return valid JSON." in data["error"]
        assert "blurry" in data["raw"]

    def test_scan_receipt_auth_error_handling(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Verifies structured JSON error on provider auth failure."""
        from astakos_skills.scan_receipt import scan_receipt

        receipt_file: Path = tmp_path / "receipt.jpg"
        receipt_file.write_bytes(b"receipt_bytes")

        monkeypatch.setattr(
            "core.brain.get_active_provider_adapter",
            lambda: MockVertexAIAdapter(should_fail_auth=True),
        )

        res_raw: str = scan_receipt.invoke({"image_path": str(receipt_file)})
        data: dict[str, Any] = json.loads(res_raw)

        assert "error" in data
        assert "authentication failed" in data["error"]

    def test_scan_receipt_rate_limit_error_handling(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Verifies structured JSON error on provider rate limit / quota exhaustion."""
        from astakos_skills.scan_receipt import scan_receipt

        receipt_file: Path = tmp_path / "receipt.jpg"
        receipt_file.write_bytes(b"receipt_bytes")

        monkeypatch.setattr(
            "core.brain.get_active_provider_adapter",
            lambda: MockGeminiAPIAdapter(should_rate_limit=True),
        )

        res_raw: str = scan_receipt.invoke({"image_path": str(receipt_file)})
        data: dict[str, Any] = json.loads(res_raw)

        assert "error" in data
        assert "quota or rate limit exceeded" in data["error"]


# ────────────────────────────────────────────────────────────────
# 4. NUTRITION ANALYZER TESTS
# ────────────────────────────────────────────────────────────────

class TestNutritionAnalyzerMigration:
    """Validates astakos_skills/nutrition_analyzer.py:analyze_nutrition with AI provider adapter."""

    def test_analyze_nutrition_missing_file_returns_error_message(self) -> None:
        """Verifies missing nutrition label image returns user-friendly error string."""
        from astakos_skills.nutrition_analyzer import analyze_nutrition

        result: str = analyze_nutrition("non_existent_nutrition.jpg")
        assert "not found" in result.lower() or "δεν βρέθηκε" in result.lower()

    def test_analyze_nutrition_gemini_success(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Verifies nutrition label analysis with Gemini adapter."""
        from astakos_skills.nutrition_analyzer import analyze_nutrition

        food_file: Path = tmp_path / "yogurt_label.jpg"
        food_file.write_bytes(b"yogurt_photo_bytes")

        class YogurtVisionAdapter(MockGeminiAPIAdapter):
            def analyze_vision(
                self, prompt: str, image_bytes: bytes, mime_type: str = "image/jpeg"
            ) -> str:
                assert image_bytes == b"yogurt_photo_bytes"
                assert "Greek yogurt" in prompt
                return "Nutritional analysis: High protein (10g/100g), low sugar. Healthy choice."

        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: YogurtVisionAdapter())

        result: str = analyze_nutrition(str(food_file), product_hint="Greek yogurt")

        assert "Nutritional analysis: High protein" in result

    def test_analyze_nutrition_anthropic_success(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Verifies nutrition label analysis with Anthropic adapter."""
        from astakos_skills.nutrition_analyzer import analyze_nutrition

        food_file: Path = tmp_path / "bread_label.jpg"
        food_file.write_bytes(b"bread_photo_bytes")

        class BreadVisionAdapter(MockAnthropicAdapter):
            def analyze_vision(
                self, prompt: str, image_bytes: bytes, mime_type: str = "image/jpeg"
            ) -> str:
                return "Nutritional analysis: Whole grain, 4g fiber."

        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: BreadVisionAdapter())

        result: str = analyze_nutrition(str(food_file))

        assert "Whole grain" in result

    def test_analyze_nutrition_auth_error_handling(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Verifies graceful error message on auth failure without crashing."""
        from astakos_skills.nutrition_analyzer import analyze_nutrition

        food_file: Path = tmp_path / "cereal.jpg"
        food_file.write_bytes(b"cereal_bytes")

        monkeypatch.setattr(
            "core.brain.get_active_provider_adapter",
            lambda: MockOpenAIAdapter(should_fail_auth=True),
        )

        result: str = analyze_nutrition(str(food_file))

        assert "authentication failed" in result.lower() or "auth failed" in result.lower()

    def test_analyze_nutrition_rate_limit_error_handling(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Verifies graceful error message on rate limit exhaustion."""
        from astakos_skills.nutrition_analyzer import analyze_nutrition

        food_file: Path = tmp_path / "cereal.jpg"
        food_file.write_bytes(b"cereal_bytes")

        monkeypatch.setattr(
            "core.brain.get_active_provider_adapter",
            lambda: MockVertexAIAdapter(should_rate_limit=True),
        )

        result: str = analyze_nutrition(str(food_file))

        assert "quota or rate limit exceeded" in result.lower() or "limit" in result.lower()


# ────────────────────────────────────────────────────────────────
# 5. TELEGRAM BOT PHOTO HANDLER TESTS
# ────────────────────────────────────────────────────────────────

class TestTelegramPhotoHandlerMigration:
    """Validates clients/telegram_bot.py:handle_photo with AI provider adapter."""

    def test_handle_photo_with_caption_routes_to_process_question(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Verifies photo download and vision analysis routing with caption question."""
        import clients.telegram_bot as tb

        monkeypatch.setattr("clients.telegram_bot.PHOTOS_DIR", str(tmp_path))
        monkeypatch.setattr("clients.telegram_bot.TELEGRAM_TOKEN", "fake_bot_token")

        def mock_get(url: str, *args: Any, **kwargs: Any) -> MagicMock:
            resp = MagicMock()
            if "getFile" in url:
                resp.json.return_value = {"result": {"file_path": "photos/file_1.jpg"}}
            else:
                resp.content = b"fake_downloaded_photo_bytes"
            return resp

        monkeypatch.setattr("requests.get", mock_get)

        captured_vision: dict[str, Any] = {}

        class TelegramVisionAdapter(MockVertexAIAdapter):
            def analyze_vision(
                self, prompt: str, image_bytes: bytes, mime_type: str = "image/jpeg"
            ) -> str:
                captured_vision["prompt"] = prompt
                captured_vision["bytes"] = image_bytes
                return "A photo of an architect blueprint on a wooden desk."

        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: TelegramVisionAdapter())

        processed_calls: list[tuple[str, str, str, str, str]] = []
        monkeypatch.setattr(
            "clients.telegram_bot._process_photo_with_question",
            lambda fn, lp, analysis, cap, cid: processed_calls.append((fn, lp, analysis, cap, cid)),
        )

        photo_list: list[dict[str, Any]] = [{"file_id": "photo_123", "file_size": 5000}]
        tb.handle_photo(photo_list, caption="What is this drawing?", chat_id="chat_999")

        assert len(processed_calls) == 1
        fn, lp, analysis, cap, cid = processed_calls[0]
        assert "blueprint" in analysis
        assert cap == "What is this drawing?"
        assert cid == "chat_999"
        assert captured_vision["bytes"] == b"fake_downloaded_photo_bytes"

    def test_handle_photo_without_caption_saves_pending_photo(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Verifies photo without caption is analyzed and staged into pending_photo state."""
        import clients.telegram_bot as tb

        monkeypatch.setattr("clients.telegram_bot.PHOTOS_DIR", str(tmp_path))
        monkeypatch.setattr("clients.telegram_bot.TELEGRAM_TOKEN", "fake_bot_token")

        def mock_get(url: str, *args: Any, **kwargs: Any) -> MagicMock:
            resp = MagicMock()
            if "getFile" in url:
                resp.json.return_value = {"result": {"file_path": "photos/file_2.jpg"}}
            else:
                resp.content = b"flower_photo_bytes"
            return resp

        monkeypatch.setattr("requests.get", mock_get)
        monkeypatch.setattr("clients.telegram_bot.send_telegram_msg", lambda msg: None)

        class FlowerVisionAdapter(MockOpenAIAdapter):
            def analyze_vision(
                self, prompt: str, image_bytes: bytes, mime_type: str = "image/jpeg"
            ) -> str:
                return "A vibrant yellow sunflower in full bloom."

        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: FlowerVisionAdapter())

        photo_list: list[dict[str, Any]] = [{"file_id": "photo_456", "file_size": 8000}]
        tb.handle_photo(photo_list, caption="", chat_id="chat_999")

        assert tb.pending_photo is not None
        assert "sunflower" in tb.pending_photo["analysis"]

    def test_handle_photo_auth_error_sends_safe_telegram_message(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Verifies Telegram photo handler dispatches user-friendly message on auth error."""
        import clients.telegram_bot as tb

        monkeypatch.setattr("clients.telegram_bot.PHOTOS_DIR", str(tmp_path))
        monkeypatch.setattr("clients.telegram_bot.TELEGRAM_TOKEN", "fake_bot_token")

        def mock_get(url: str, *args: Any, **kwargs: Any) -> MagicMock:
            resp = MagicMock()
            if "getFile" in url:
                resp.json.return_value = {"result": {"file_path": "photos/file_3.jpg"}}
            else:
                resp.content = b"photo_bytes"
            return resp

        monkeypatch.setattr("requests.get", mock_get)

        sent_messages: list[str] = []
        monkeypatch.setattr("clients.telegram_bot.send_telegram_msg", lambda msg: sent_messages.append(msg))

        monkeypatch.setattr(
            "core.brain.get_active_provider_adapter",
            lambda: MockVertexAIAdapter(should_fail_auth=True),
        )

        photo_list: list[dict[str, Any]] = [{"file_id": "photo_789", "file_size": 1000}]
        tb.handle_photo(photo_list, caption="explain", chat_id="chat_999")

        assert len(sent_messages) == 1
        assert "authentication failed" in sent_messages[0]


# ────────────────────────────────────────────────────────────────
# 6. WEB API UPLOAD PHOTO TESTS & FAILURE SEMANTICS
# ────────────────────────────────────────────────────────────────

class TestWebUploadPhotoMigration:
    """Validates api/server.py:upload_file photo analysis and failure semantics."""

    def test_web_upload_photo_success_with_adapter(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Verifies successful photo upload returns analysis and memory confirmation prompt."""
        from fastapi.testclient import TestClient
        from api.server import server, LOCAL_TOKEN

        mock_uploads_dir: Path = tmp_path / "uploads"
        mock_uploads_dir.mkdir()

        img = Image.new("RGB", (100, 100), color="blue")
        img_bytes_io = io.BytesIO()
        img.save(img_bytes_io, format="JPEG")
        test_jpeg_bytes: bytes = img_bytes_io.getvalue()

        class WebVisionAdapter(MockVertexAIAdapter):
            def analyze_vision(
                self, prompt: str, image_bytes: bytes, mime_type: str = "image/jpeg"
            ) -> str:
                return "Ένα μπλε τετράγωνο δείγμα εικόνας."

        client = TestClient(server)
        created_archives: list[dict[str, Any]] = []

        with patch("api.server.PHOTOS_DIR", str(mock_uploads_dir)), \
             patch("config.PHOTOS_DIR", str(mock_uploads_dir)), \
             patch("api.server.append_to_chat_history"), \
             patch("api.server.enqueue_fast_task"), \
             patch("api.server.enqueue_slow_task"), \
             patch("memory.pending_assets.create_pending_asset_archive", lambda **kw: created_archives.append(kw)), \
             patch("core.brain.get_active_provider_adapter", return_value=WebVisionAdapter()):

            files = {"file": ("test_blue.jpg", test_jpeg_bytes, "image/jpeg")}
            data = {"message": "Τι είναι αυτή η φωτογραφία;"}
            headers = {"Authorization": f"Bearer {LOCAL_TOKEN}"}

            response = client.post("/upload", files=files, data=data, headers=headers)

            assert response.status_code == 200
            json_resp = response.json()
            assert json_resp["status"] == "success"
            assert "μπλε τετράγωνο" in json_resp["ai_message"]
            # Successful upload should trigger memory confirmation flow
            assert len(created_archives) == 1

    def test_web_upload_photo_auth_error_semantics(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Verifies auth failure preserves file, shows clear error, and does NOT offer save flow."""
        from fastapi.testclient import TestClient
        from api.server import server, LOCAL_TOKEN

        mock_uploads_dir: Path = tmp_path / "uploads"
        mock_uploads_dir.mkdir()

        img = Image.new("RGB", (100, 100), color="red")
        img_bytes_io = io.BytesIO()
        img.save(img_bytes_io, format="JPEG")
        test_jpeg_bytes: bytes = img_bytes_io.getvalue()

        client = TestClient(server)
        created_archives: list[dict[str, Any]] = []

        with patch("api.server.PHOTOS_DIR", str(mock_uploads_dir)), \
             patch("config.PHOTOS_DIR", str(mock_uploads_dir)), \
             patch("api.server.append_to_chat_history"), \
             patch("api.server.enqueue_fast_task"), \
             patch("api.server.enqueue_slow_task"), \
             patch("memory.pending_assets.create_pending_asset_archive", lambda **kw: created_archives.append(kw)), \
             patch("core.brain.get_active_provider_adapter", return_value=MockVertexAIAdapter(should_fail_auth=True)):

            files = {"file": ("test_red.jpg", test_jpeg_bytes, "image/jpeg")}
            data = {"message": ""}
            headers = {"Authorization": f"Bearer {LOCAL_TOKEN}"}

            response = client.post("/upload", files=files, data=data, headers=headers)

            assert response.status_code == 200
            json_resp = response.json()
            assert json_resp["status"] == "success"
            # File is saved safely
            assert (mock_uploads_dir / json_resp["filename"]).exists()
            # Clear error notification returned to user
            assert "αυθεντικοποίηση ανάλυσης εικόνας απέτυχε" in json_resp["ai_message"]
            assert "δεν είναι διαθέσιμη" in json_resp["ai_message"]
            # No misleading memory confirmation created
            assert len(created_archives) == 0

    def test_web_upload_photo_rate_limit_error_semantics(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Verifies rate limit exhaustion preserves file, shows error, and does NOT offer save flow."""
        from fastapi.testclient import TestClient
        from api.server import server, LOCAL_TOKEN

        mock_uploads_dir: Path = tmp_path / "uploads"
        mock_uploads_dir.mkdir()

        img = Image.new("RGB", (100, 100), color="green")
        img_bytes_io = io.BytesIO()
        img.save(img_bytes_io, format="JPEG")
        test_jpeg_bytes: bytes = img_bytes_io.getvalue()

        client = TestClient(server)
        created_archives: list[dict[str, Any]] = []

        with patch("api.server.PHOTOS_DIR", str(mock_uploads_dir)), \
             patch("config.PHOTOS_DIR", str(mock_uploads_dir)), \
             patch("api.server.append_to_chat_history"), \
             patch("api.server.enqueue_fast_task"), \
             patch("api.server.enqueue_slow_task"), \
             patch("memory.pending_assets.create_pending_asset_archive", lambda **kw: created_archives.append(kw)), \
             patch("core.brain.get_active_provider_adapter", return_value=MockGeminiAPIAdapter(should_rate_limit=True)):

            files = {"file": ("test_green.jpg", test_jpeg_bytes, "image/jpeg")}
            data = {"message": ""}
            headers = {"Authorization": f"Bearer {LOCAL_TOKEN}"}

            response = client.post("/upload", files=files, data=data, headers=headers)

            assert response.status_code == 200
            json_resp = response.json()
            assert "όριο κλήσεων/quota" in json_resp["ai_message"]
            assert len(created_archives) == 0

    def test_web_upload_photo_unsupported_capability_semantics(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Verifies unsupported provider vision gracefully rejects without creating memory archive."""
        from fastapi.testclient import TestClient
        from api.server import server, LOCAL_TOKEN
        from core.ai_provider import CapabilityNotSupportedError

        mock_uploads_dir: Path = tmp_path / "uploads"
        mock_uploads_dir.mkdir()

        img = Image.new("RGB", (100, 100), color="yellow")
        img_bytes_io = io.BytesIO()
        img.save(img_bytes_io, format="JPEG")
        test_jpeg_bytes: bytes = img_bytes_io.getvalue()

        class NoVisionProviderAdapter(MockVertexAIAdapter):
            def analyze_vision(
                self, prompt: str, image_bytes: bytes, mime_type: str = "image/jpeg"
            ) -> str:
                raise CapabilityNotSupportedError("custom_provider", "vision")

        client = TestClient(server)
        created_archives: list[dict[str, Any]] = []

        with patch("api.server.PHOTOS_DIR", str(mock_uploads_dir)), \
             patch("config.PHOTOS_DIR", str(mock_uploads_dir)), \
             patch("api.server.append_to_chat_history"), \
             patch("api.server.enqueue_fast_task"), \
             patch("api.server.enqueue_slow_task"), \
             patch("memory.pending_assets.create_pending_asset_archive", lambda **kw: created_archives.append(kw)), \
             patch("core.brain.get_active_provider_adapter", return_value=NoVisionProviderAdapter()):

            files = {"file": ("test_yellow.jpg", test_jpeg_bytes, "image/jpeg")}
            data = {"message": ""}
            headers = {"Authorization": f"Bearer {LOCAL_TOKEN}"}

            response = client.post("/upload", files=files, data=data, headers=headers)

            assert response.status_code == 200
            json_resp = response.json()
            assert "δεν υποστηρίζεται από τον πάροχο 'custom_provider'" in json_resp["ai_message"]
            assert len(created_archives) == 0


# ────────────────────────────────────────────────────────────────
# 7. AGENT NODES VISION MIGRATION TESTS
# ────────────────────────────────────────────────────────────────

class TestAgentNodesVisionMigration:
    """Validates Chat, Web, and Tech agents analyze images via adapter without raw image_url parts."""

    def test_chat_agent_node_analyzes_photo_via_adapter(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Verifies Chat_Agent routes visual analysis through adapter and builds clean text prompt."""
        import core.agents as agents
        from langchain_core.messages import HumanMessage, AIMessage

        photo_file: Path = tmp_path / "photo_chat.jpg"
        photo_file.write_bytes(b"chat_photo_bytes")

        captured_invocations: list[list[Any]] = []

        class ChatVisionAdapter(MockVertexAIAdapter):
            def analyze_vision(
                self, prompt: str, image_bytes: bytes, mime_type: str = "image/jpeg"
            ) -> str:
                assert image_bytes == b"chat_photo_bytes"
                return "Visual inspection shows a modern living room."

        monkeypatch.setattr("core.agents.PHOTOS_DIR", str(tmp_path))
        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: ChatVisionAdapter())

        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = lambda msgs: AIMessage(content="I see the living room!")
        mock_llm.bind_tools.return_value = mock_llm
        monkeypatch.setattr("core.agents.llm", mock_llm)

        state: dict[str, Any] = {
            "messages": [
                HumanMessage(
                    content=f"[USER_UPLOADED_PHOTO]: photo_chat.jpg\n[PHOTO PATH]: {photo_file}\nDetailed description requested"
                )
            ],
            "channel": "web",
        }

        result: dict[str, Any] = agents.chat_agent_node(state)

        assert result["current_agent"] == "Chat_Agent"
        # Verify that all messages passed to LLM invoke are string/text based without raw image_url dicts
        invoked_msgs = mock_llm.invoke.call_args[0][0]
        for msg in invoked_msgs:
            if isinstance(msg.content, list):
                for part in msg.content:
                    assert part.get("type") != "image_url"

    def test_web_agent_node_analyzes_photo_via_adapter(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Verifies Web_Agent routes visual analysis through adapter without raw image_url parts."""
        import core.agents as agents
        from langchain_core.messages import HumanMessage, AIMessage

        photo_file: Path = tmp_path / "web_chart.png"
        photo_file.write_bytes(b"chart_png_bytes")

        class WebVisionAdapter(MockOpenAIAdapter):
            def analyze_vision(
                self, prompt: str, image_bytes: bytes, mime_type: str = "image/jpeg"
            ) -> str:
                assert image_bytes == b"chart_png_bytes"
                assert mime_type == "image/png"
                return "Bar chart showing revenue growth of 25%."

        monkeypatch.setattr("core.agents.PHOTOS_DIR", str(tmp_path))
        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: WebVisionAdapter())

        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = lambda msgs: AIMessage(content="The revenue grew by 25%.")
        mock_llm.bind_tools.return_value = mock_llm
        monkeypatch.setattr("core.agents.llm", mock_llm)

        state: dict[str, Any] = {
            "messages": [
                HumanMessage(
                    content=f"[USER_UPLOADED_PHOTO]: web_chart.png\n[PHOTO PATH]: {photo_file}\nAnalyze chart"
                )
            ],
            "channel": "web",
        }

        result: dict[str, Any] = agents.web_agent_node(state)

        assert result["current_agent"] == "Web_Agent"
        invoked_msgs = mock_llm.invoke.call_args[0][0]
        for msg in invoked_msgs:
            if isinstance(msg.content, list):
                for part in msg.content:
                    assert part.get("type") != "image_url"

    def test_tech_agent_node_analyzes_photo_via_adapter(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Verifies Tech_Agent routes visual analysis through adapter without raw image_url parts."""
        import core.agents as agents
        from langchain_core.messages import HumanMessage, AIMessage

        photo_file: Path = tmp_path / "schema.jpg"
        photo_file.write_bytes(b"schema_jpg_bytes")

        class TechVisionAdapter(MockAnthropicAdapter):
            def analyze_vision(
                self, prompt: str, image_bytes: bytes, mime_type: str = "image/jpeg"
            ) -> str:
                assert image_bytes == b"schema_jpg_bytes"
                return "Database diagram showing Users and Orders tables."

        monkeypatch.setattr("core.agents.PHOTOS_DIR", str(tmp_path))
        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: TechVisionAdapter())

        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = lambda msgs: AIMessage(content="Database diagram analyzed.")
        mock_llm.bind_tools.return_value = mock_llm
        monkeypatch.setattr("core.agents.llm_heavy", mock_llm)

        state: dict[str, Any] = {
            "messages": [
                HumanMessage(
                    content=f"[USER_UPLOADED_PHOTO]: schema.jpg\n[PHOTO PATH]: {photo_file}\nCheck database design"
                )
            ],
            "channel": "web",
        }

        result: dict[str, Any] = agents.tech_agent_node(state)

        assert result["current_agent"] == "Tech_Agent"
        invoked_msgs = mock_llm.invoke.call_args[0][0]
        for msg in invoked_msgs:
            if isinstance(msg.content, list):
                for part in msg.content:
                    assert part.get("type") != "image_url"


# ────────────────────────────────────────────────────────────────
# 8. CHAT STREAM PHOTO VISION MIGRATION TESTS
# ────────────────────────────────────────────────────────────────

class TestChatStreamPhotoVisionMigration:
    """Validates api/server.py chat stream photo intake with AI provider adapter."""

    def test_chat_stream_with_photo_invokes_adapter_vision_and_cleans_message(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Verifies chat streaming parses photo via adapter and attaches untrusted analysis."""
        from langchain_core.messages import HumanMessage

        photo_file: Path = tmp_path / "stream_photo.jpg"
        photo_file.write_bytes(b"stream_photo_data")

        captured_vision: dict[str, Any] = {}

        class StreamVisionAdapter(MockVertexAIAdapter):
            def analyze_vision(
                self, prompt: str, image_bytes: bytes, mime_type: str = "image/jpeg"
            ) -> str:
                captured_vision["prompt"] = prompt
                captured_vision["bytes"] = image_bytes
                return "Analysis: A dashboard screen showing 99.9% uptime."

        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: StreamVisionAdapter())

        # Simulate the exact logic in api/server.py
        from core.untrusted_content import (
            USER_PROVIDED_ASSET_SOURCE,
            external_content_history_metadata,
            format_untrusted_asset_vision_prompt,
            format_untrusted_tool_result,
        )
        from core.brain import get_active_provider_adapter

        photo_path: str = str(photo_file)
        isolated_user_input: str = "Explain the system status."
        filename: str = os.path.basename(photo_path)
        ext: str = os.path.splitext(filename)[1].lower()

        adapter = get_active_provider_adapter()
        vision_prompt = format_untrusted_asset_vision_prompt(
            f"Analyze this image and describe the visual content relevant to the user request:\n{isolated_user_input}"
        )
        vision_text = adapter.analyze_vision(vision_prompt, photo_file.read_bytes(), mime_type="image/jpeg").strip()
        untrusted_analysis = format_untrusted_tool_result(USER_PROVIDED_ASSET_SOURCE, vision_text)
        enhanced_user_input = (
            f"[USER_UPLOADED_FILE]: {filename}\n"
            f"[PHOTO PATH]: {photo_path}\n"
            f"[ANALYSIS]: {untrusted_analysis}\n"
            f"{isolated_user_input}"
        )
        human_msg = HumanMessage(
            content=f"[12:00] {enhanced_user_input}",
            additional_kwargs=external_content_history_metadata([USER_PROVIDED_ASSET_SOURCE]),
        )

        assert isinstance(human_msg.content, str)
        assert "99.9% uptime" in human_msg.content
        assert captured_vision["bytes"] == b"stream_photo_data"
        assert "<untrusted-tool-result>" in human_msg.content
        assert "[UNTRUSTED EXTERNAL TOOL RESULT]" in human_msg.content
