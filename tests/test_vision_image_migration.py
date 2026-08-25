# ================================================================
# Project: Astakos AI Agent 🦞
# Test Suite: Vision Analysis & Image Generation Migration (PR 3C)
# Description: Validates deterministic offline behavior for all
#              migrated vision and image generation call sites.
# ================================================================

import json
import os
import pytest
from unittest.mock import patch, MagicMock

from core.ai_provider import (
    CapabilityNotSupportedError,
    ProviderAuthError,
    RateLimitError,
    AIProviderError,
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

    def test_generate_image_tool_vertex_success(self, monkeypatch, tmp_path):
        import tools.system as sys_tools

        monkeypatch.setattr("config.BASE_DIR", str(tmp_path))
        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: MockVertexAIAdapter())

        result = sys_tools.generate_image_tool.invoke({"prompt": "a cute little lobster in a garden"})

        assert result.startswith("✅ Ready! Image created.")
        assert "[SEND_PHOTO:" in result
        out_path = result.split("[SEND_PHOTO:")[1].replace("]", "").strip()
        assert os.path.exists(out_path)
        with open(out_path, "rb") as f:
            assert f.read() == b"\xff\xd8\xff\xe0\x00\x10JFIF\x00mock_vertex_image"

    def test_generate_image_tool_openai_success(self, monkeypatch, tmp_path):
        import tools.system as sys_tools

        monkeypatch.setattr("config.BASE_DIR", str(tmp_path))
        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: MockOpenAIAdapter())

        result = sys_tools.generate_image_tool.invoke({"prompt": "cyberpunk city landscape"})

        assert result.startswith("✅ Ready! Image created.")
        assert "[SEND_PHOTO:" in result
        out_path = result.split("[SEND_PHOTO:")[1].replace("]", "").strip()
        assert os.path.exists(out_path)
        with open(out_path, "rb") as f:
            assert f.read() == b"\xff\xd8\xff\xe0\x00\x10JFIF\x00mock_openai_image"

    def test_generate_image_tool_anthropic_unsupported(self, monkeypatch, tmp_path):
        import tools.system as sys_tools

        monkeypatch.setattr("config.BASE_DIR", str(tmp_path))
        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: MockAnthropicAdapter())

        result = sys_tools.generate_image_tool.invoke({"prompt": "a futuristic robot"})

        assert "❌ Image generation is not supported by provider 'anthropic'" in result

    def test_generate_image_tool_auth_error(self, monkeypatch, tmp_path):
        import tools.system as sys_tools

        monkeypatch.setattr("config.BASE_DIR", str(tmp_path))
        monkeypatch.setattr(
            "core.brain.get_active_provider_adapter",
            lambda: MockVertexAIAdapter(should_fail_auth=True),
        )

        result = sys_tools.generate_image_tool.invoke({"prompt": "a painting"})

        assert "❌ Image generation authentication failed for provider 'vertex'" in result

    def test_generate_image_tool_rate_limit_error(self, monkeypatch, tmp_path):
        import tools.system as sys_tools

        monkeypatch.setattr("config.BASE_DIR", str(tmp_path))
        monkeypatch.setattr(
            "core.brain.get_active_provider_adapter",
            lambda: MockGeminiAPIAdapter(should_rate_limit=True),
        )

        result = sys_tools.generate_image_tool.invoke({"prompt": "a painting"})

        assert "❌ Image generation quota or rate limit exceeded for provider 'gemini'" in result

    def test_generate_image_tool_empty_bytes_handling(self, monkeypatch, tmp_path):
        import tools.system as sys_tools

        class EmptyImageAdapter(MockVertexAIAdapter):
            def generate_image(self, prompt, aspect_ratio="1:1"):
                return b""

        monkeypatch.setattr("config.BASE_DIR", str(tmp_path))
        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: EmptyImageAdapter())

        result = sys_tools.generate_image_tool.invoke({"prompt": "a sketch"})

        assert "❌ Image generation error (vertex): provider returned no image data." in result



# ────────────────────────────────────────────────────────────────
# 2. STORY MAKER IMAGE GENERATION TESTS
# ────────────────────────────────────────────────────────────────

class TestStoryMakerImageMigration:
    """Validates astakos_skills/story_maker._generate_image with AI provider adapter."""

    def test_story_maker_generate_image_vertex_success(self, monkeypatch, tmp_path):
        import astakos_skills.story_maker as sm

        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: MockVertexAIAdapter())

        path = sm._generate_image("a magical forest with unicorns", str(tmp_path), 1)

        assert path is not None
        assert os.path.exists(path)
        assert path.endswith(".jpg")
        with open(path, "rb") as f:
            assert f.read() == b"\xff\xd8\xff\xe0\x00\x10JFIF\x00mock_vertex_image"

    def test_story_maker_generate_image_openai_success(self, monkeypatch, tmp_path):
        import astakos_skills.story_maker as sm

        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: MockOpenAIAdapter())

        path = sm._generate_image("a cute bear catching fish", str(tmp_path), 2)

        assert path is not None
        assert os.path.exists(path)
        with open(path, "rb") as f:
            assert f.read() == b"\xff\xd8\xff\xe0\x00\x10JFIF\x00mock_openai_image"

    def test_story_maker_generate_image_anthropic_unsupported_returns_none(self, monkeypatch, tmp_path):
        import astakos_skills.story_maker as sm

        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: MockAnthropicAdapter())

        path = sm._generate_image("scene prompt", str(tmp_path), 1)

        assert path is None

    def test_story_maker_generate_image_auth_error_returns_none(self, monkeypatch, tmp_path):
        import astakos_skills.story_maker as sm

        monkeypatch.setattr(
            "core.brain.get_active_provider_adapter",
            lambda: MockVertexAIAdapter(should_fail_auth=True),
        )

        path = sm._generate_image("scene prompt", str(tmp_path), 1)

        assert path is None

    def test_make_story_full_flow_with_adapter_images(self, monkeypatch, tmp_path):
        import astakos_skills.story_maker as sm

        class StoryAndImageAdapter(MockVertexAIAdapter):
            def generate_text(self, prompt, model_type="fast", system_prompt=None, temperature=None):
                return (
                    "Once upon a time in a enchanted valley.\n"
                    "SCENE1: A peaceful enchanted valley with rivers\n"
                    "SCENE2: A young explorer discovering a hidden crystal\n"
                    "SCENE3: The valley glowing under starry skies"
                )

        monkeypatch.setattr("config.BASE_DIR", str(tmp_path))
        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: StoryAndImageAdapter())
        monkeypatch.setattr("time.sleep", lambda s: None)

        result = sm.make_story("enchanted valley")

        assert result["error"] is None
        assert result["story"] == "Once upon a time in a enchanted valley."
        assert len(result["images"]) == 3
        for img_p in result["images"]:
            assert os.path.exists(img_p)


# ────────────────────────────────────────────────────────────────
# 3. SCAN RECEIPT TESTS
# ────────────────────────────────────────────────────────────────

class TestScanReceiptMigration:
    """Validates astakos_skills/scan_receipt.py:scan_receipt with AI provider adapter."""

    def test_scan_receipt_missing_file_returns_error_json(self):
        from astakos_skills.scan_receipt import scan_receipt

        res_raw = scan_receipt.invoke({"image_path": "non_existent_receipt.jpg"})
        data = json.loads(res_raw)
        assert "error" in data
        assert "not found" in data["error"]

    def test_scan_receipt_vertex_success(self, monkeypatch, tmp_path):
        from astakos_skills.scan_receipt import scan_receipt

        receipt_file = tmp_path / "supermarket_receipt.jpg"
        receipt_file.write_bytes(b"\xff\xd8\xff\xe0mock_jpeg_receipt")

        receipt_payload = {
            "store": "SuperMarket Alpha",
            "date": "2026-08-25",
            "total": 42.50,
            "items": [
                {"name": "Milk", "qty": 2, "price": 3.20},
                {"name": "Bread", "qty": 1, "price": 1.10},
            ],
        }

        class ReceiptVisionAdapter(MockVertexAIAdapter):
            def analyze_vision(self, prompt, image_bytes, mime_type="image/jpeg"):
                assert image_bytes == b"\xff\xd8\xff\xe0mock_jpeg_receipt"
                return f"```json\n{json.dumps(receipt_payload)}\n```"

        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: ReceiptVisionAdapter())

        res_raw = scan_receipt.invoke({"image_path": str(receipt_file)})
        data = json.loads(res_raw)

        assert data["store"] == "SuperMarket Alpha"
        assert data["total"] == 42.50
        assert len(data["items"]) == 2

    def test_scan_receipt_anthropic_vision_success(self, monkeypatch, tmp_path):
        from astakos_skills.scan_receipt import scan_receipt

        receipt_file = tmp_path / "coffee_receipt.jpg"
        receipt_file.write_bytes(b"mock_receipt_bytes")

        receipt_payload = {
            "store": "Cafe Delight",
            "date": "2026-08-25",
            "total": 4.50,
            "items": [{"name": "Espresso", "qty": 1, "price": 4.50}],
        }

        class AnthropicReceiptAdapter(MockAnthropicAdapter):
            def analyze_vision(self, prompt, image_bytes, mime_type="image/jpeg"):
                return json.dumps(receipt_payload)

        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: AnthropicReceiptAdapter())

        res_raw = scan_receipt.invoke({"image_path": str(receipt_file)})
        data = json.loads(res_raw)

        assert data["store"] == "Cafe Delight"
        assert data["total"] == 4.50

    def test_scan_receipt_non_json_model_response(self, monkeypatch, tmp_path):
        from astakos_skills.scan_receipt import scan_receipt

        receipt_file = tmp_path / "blurry_receipt.jpg"
        receipt_file.write_bytes(b"blurry_bytes")

        class BlurryReceiptAdapter(MockOpenAIAdapter):
            def analyze_vision(self, prompt, image_bytes, mime_type="image/jpeg"):
                return "The receipt is too blurry to extract items."

        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: BlurryReceiptAdapter())

        res_raw = scan_receipt.invoke({"image_path": str(receipt_file)})
        data = json.loads(res_raw)

        assert "error" in data
        assert "Model did not return valid JSON." in data["error"]
        assert "blurry" in data["raw"]

    def test_scan_receipt_auth_error_handling(self, monkeypatch, tmp_path):
        from astakos_skills.scan_receipt import scan_receipt

        receipt_file = tmp_path / "receipt.jpg"
        receipt_file.write_bytes(b"receipt_bytes")

        monkeypatch.setattr(
            "core.brain.get_active_provider_adapter",
            lambda: MockVertexAIAdapter(should_fail_auth=True),
        )

        res_raw = scan_receipt.invoke({"image_path": str(receipt_file)})
        data = json.loads(res_raw)

        assert "error" in data
        assert "authentication failed" in data["error"]


# ────────────────────────────────────────────────────────────────
# 4. NUTRITION ANALYZER TESTS
# ────────────────────────────────────────────────────────────────

class TestNutritionAnalyzerMigration:
    """Validates astakos_skills/nutrition_analyzer.py:analyze_nutrition with AI provider adapter."""

    def test_analyze_nutrition_missing_file_returns_error_message(self):
        from astakos_skills.nutrition_analyzer import analyze_nutrition

        result = analyze_nutrition("non_existent_nutrition.jpg")
        assert "not found" in result.lower() or "δεν βρέθηκε" in result.lower()

    def test_analyze_nutrition_gemini_success(self, monkeypatch, tmp_path):
        from astakos_skills.nutrition_analyzer import analyze_nutrition

        food_file = tmp_path / "yogurt_label.jpg"
        food_file.write_bytes(b"yogurt_photo_bytes")

        class YogurtVisionAdapter(MockGeminiAPIAdapter):
            def analyze_vision(self, prompt, image_bytes, mime_type="image/jpeg"):
                assert image_bytes == b"yogurt_photo_bytes"
                assert "Greek yogurt" in prompt
                return "Nutritional analysis: High protein (10g/100g), low sugar. Healthy choice."

        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: YogurtVisionAdapter())

        result = analyze_nutrition(str(food_file), product_hint="Greek yogurt")

        assert "Nutritional analysis: High protein" in result

    def test_analyze_nutrition_auth_error_handling(self, monkeypatch, tmp_path):
        from astakos_skills.nutrition_analyzer import analyze_nutrition

        food_file = tmp_path / "cereal.jpg"
        food_file.write_bytes(b"cereal_bytes")

        monkeypatch.setattr(
            "core.brain.get_active_provider_adapter",
            lambda: MockOpenAIAdapter(should_fail_auth=True),
        )

        result = analyze_nutrition(str(food_file))

        assert "authentication failed" in result.lower() or "auth failed" in result.lower()

    def test_analyze_nutrition_rate_limit_error_handling(self, monkeypatch, tmp_path):
        from astakos_skills.nutrition_analyzer import analyze_nutrition

        food_file = tmp_path / "cereal.jpg"
        food_file.write_bytes(b"cereal_bytes")

        monkeypatch.setattr(
            "core.brain.get_active_provider_adapter",
            lambda: MockVertexAIAdapter(should_rate_limit=True),
        )

        result = analyze_nutrition(str(food_file))

        assert "quota or rate limit exceeded" in result.lower() or "limit" in result.lower()


# ────────────────────────────────────────────────────────────────
# 5. TELEGRAM BOT PHOTO HANDLER TESTS
# ────────────────────────────────────────────────────────────────

class TestTelegramPhotoHandlerMigration:
    """Validates clients/telegram_bot.py:handle_photo with AI provider adapter."""

    def test_handle_photo_with_caption_routes_to_process_question(self, monkeypatch, tmp_path):
        import clients.telegram_bot as tb

        monkeypatch.setattr("clients.telegram_bot.PHOTOS_DIR", str(tmp_path))
        monkeypatch.setattr("clients.telegram_bot.TELEGRAM_TOKEN", "fake_bot_token")

        # Mock Telegram getFile & download requests
        def mock_get(url, *args, **kwargs):
            resp = MagicMock()
            if "getFile" in url:
                resp.json.return_value = {"result": {"file_path": "photos/file_1.jpg"}}
            else:
                resp.content = b"fake_downloaded_photo_bytes"
            return resp

        monkeypatch.setattr("requests.get", mock_get)

        captured_vision = {}

        class TelegramVisionAdapter(MockVertexAIAdapter):
            def analyze_vision(self, prompt, image_bytes, mime_type="image/jpeg"):
                captured_vision["prompt"] = prompt
                captured_vision["bytes"] = image_bytes
                return "A photo of an architect blueprint on a wooden desk."

        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: TelegramVisionAdapter())

        processed_calls = []
        monkeypatch.setattr(
            "clients.telegram_bot._process_photo_with_question",
            lambda fn, lp, analysis, cap, cid: processed_calls.append((fn, lp, analysis, cap, cid)),
        )

        photo_list = [{"file_id": "photo_123", "file_size": 5000}]
        tb.handle_photo(photo_list, caption="What is this drawing?", chat_id="chat_999")

        assert len(processed_calls) == 1
        fn, lp, analysis, cap, cid = processed_calls[0]
        assert "blueprint" in analysis
        assert cap == "What is this drawing?"
        assert cid == "chat_999"
        assert captured_vision["bytes"] == b"fake_downloaded_photo_bytes"

    def test_handle_photo_without_caption_saves_pending_photo(self, monkeypatch, tmp_path):
        import clients.telegram_bot as tb

        monkeypatch.setattr("clients.telegram_bot.PHOTOS_DIR", str(tmp_path))
        monkeypatch.setattr("clients.telegram_bot.TELEGRAM_TOKEN", "fake_bot_token")

        def mock_get(url, *args, **kwargs):
            resp = MagicMock()
            if "getFile" in url:
                resp.json.return_value = {"result": {"file_path": "photos/file_2.jpg"}}
            else:
                resp.content = b"flower_photo_bytes"
            return resp

        monkeypatch.setattr("requests.get", mock_get)
        monkeypatch.setattr("clients.telegram_bot.send_telegram_msg", lambda msg: None)

        class FlowerVisionAdapter(MockOpenAIAdapter):
            def analyze_vision(self, prompt, image_bytes, mime_type="image/jpeg"):
                return "A vibrant yellow sunflower in full bloom."

        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: FlowerVisionAdapter())

        photo_list = [{"file_id": "photo_456", "file_size": 8000}]
        tb.handle_photo(photo_list, caption="", chat_id="chat_999")

        assert tb.pending_photo is not None
        assert "sunflower" in tb.pending_photo["analysis"]

    def test_handle_photo_auth_error_sends_safe_telegram_message(self, monkeypatch, tmp_path):
        import clients.telegram_bot as tb

        monkeypatch.setattr("clients.telegram_bot.PHOTOS_DIR", str(tmp_path))
        monkeypatch.setattr("clients.telegram_bot.TELEGRAM_TOKEN", "fake_bot_token")

        def mock_get(url, *args, **kwargs):
            resp = MagicMock()
            if "getFile" in url:
                resp.json.return_value = {"result": {"file_path": "photos/file_3.jpg"}}
            else:
                resp.content = b"photo_bytes"
            return resp

        monkeypatch.setattr("requests.get", mock_get)

        sent_messages = []
        monkeypatch.setattr("clients.telegram_bot.send_telegram_msg", lambda msg: sent_messages.append(msg))

        monkeypatch.setattr(
            "core.brain.get_active_provider_adapter",
            lambda: MockVertexAIAdapter(should_fail_auth=True),
        )

        photo_list = [{"file_id": "photo_789", "file_size": 1000}]
        tb.handle_photo(photo_list, caption="explain", chat_id="chat_999")

        assert len(sent_messages) == 1
        assert "authentication failed" in sent_messages[0]


# ────────────────────────────────────────────────────────────────
# 6. WEB API UPLOAD PHOTO TESTS
# ────────────────────────────────────────────────────────────────

class TestWebUploadPhotoMigration:
    """Validates api/server.py:upload_file photo analysis with AI provider adapter."""

    def test_web_upload_photo_success_with_adapter(self, monkeypatch, tmp_path):
        from fastapi.testclient import TestClient
        from api.server import server, LOCAL_TOKEN
        from PIL import Image
        import io

        mock_uploads_dir = tmp_path / "uploads"
        mock_uploads_dir.mkdir()

        # Create a small valid JPEG image
        img = Image.new("RGB", (100, 100), color="blue")
        img_bytes_io = io.BytesIO()
        img.save(img_bytes_io, format="JPEG")
        test_jpeg_bytes = img_bytes_io.getvalue()

        class WebVisionAdapter(MockVertexAIAdapter):
            def analyze_vision(self, prompt, image_bytes, mime_type="image/jpeg"):
                return "Ένα μπλε τετράγωνο δείγμα εικόνας."

        client = TestClient(server)

        with patch("config.UPLOADS_DIR", str(mock_uploads_dir)), \
             patch("api.server.append_to_chat_history"), \
             patch("api.server.enqueue_fast_task"), \
             patch("api.server.enqueue_slow_task"), \
             patch("memory.pending_assets.create_pending_asset_archive"), \
             patch("core.brain.get_active_provider_adapter", return_value=WebVisionAdapter()):

            files = {"file": ("test_blue.jpg", test_jpeg_bytes, "image/jpeg")}
            data = {"message": "Τι είναι αυτή η φωτογραφία;"}
            headers = {"Authorization": f"Bearer {LOCAL_TOKEN}"}

            response = client.post("/upload", files=files, data=data, headers=headers)

            assert response.status_code == 200
            json_resp = response.json()
            assert json_resp["status"] == "success"
            assert "μπλε τετράγωνο" in json_resp["ai_message"]
