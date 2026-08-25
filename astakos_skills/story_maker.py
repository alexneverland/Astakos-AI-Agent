# ================================================================
# Project: Astakos AI Agent 🦞
# Skill: Story Maker for children
# Generates a fairy tale + 3 scene images via active AI provider
# ================================================================

import os
import re
import time
import json
from core.i18n import t

# ── AI provider image generator ─────────────────────────────────
def _generate_image(prompt: str, output_dir: str, index: int) -> str | None:
    """Creates a story scene image using the active AI provider adapter. Returns the path, or None if it fails."""
    try:
        from core.ai_provider import (
            CapabilityNotSupportedError,
            ProviderAuthError,
            RateLimitError,
            AIProviderError,
        )
        from core.brain import get_active_provider_adapter

        # Children's style: drawing, vibrant colors, happy
        styled = (
            f"{prompt}, children's book illustration, watercolor, "
            f"colorful, cute, magical, soft lighting, 6 year old friendly, "
            f"no text, no letters"
        )
        adapter = get_active_provider_adapter()
        img_bytes = adapter.generate_image(styled, aspect_ratio="1:1")
        if img_bytes:
            fname = os.path.join(output_dir, f"story_img_{index}_{int(time.time())}.jpg")
            with open(fname, "wb") as f:
                f.write(img_bytes)
            return fname
    except CapabilityNotSupportedError as exc:
        print(f"⚠️ [StoryMaker] Image generation not supported by provider '{exc.provider}': {exc}")
    except (ProviderAuthError, RateLimitError, AIProviderError) as exc:
        print(f"⚠️ [StoryMaker] Image {index} provider error ({getattr(exc, 'provider', 'unknown')}): {exc}")
    except Exception as e:
        print(f"⚠️ [StoryMaker] Image {index} failed: {e}")
    return None



# ── LLM story + scene prompts ────────────────────────────────────
def _generate_story_and_prompts(theme: str, characters: str = "") -> dict:
    """Calls the active AI provider for a fairy tale + 3 image prompts."""
    try:
        from core.ai_provider import (
            CapabilityNotSupportedError,
            ProviderAuthError,
            RateLimitError,
            AIProviderError,
        )
        from core.brain import get_active_provider_adapter

        char_hint = t("skills.story_maker.msg_char_hint", chars=characters) if characters else ""
        from core.utils import load_agent_prompt
        base_prompt = load_agent_prompt("story_maker")
        system_prompt = base_prompt.format(char_hint=char_hint)

        adapter = get_active_provider_adapter()
        raw = adapter.generate_text(
            f"Story theme: {theme}\n\n{system_prompt}",
            model_type="fast",
        )
        if not raw:
            return {"story": None, "scenes": []}

        raw = raw.strip()

        # Split fairytale into scenes
        scenes = []
        story_lines = []
        for line in raw.splitlines():
            m = re.match(r"SCENE\d:\s*(.+)", line.strip())
            if m:
                scenes.append(m.group(1).strip())
            else:
                story_lines.append(line)

        story_text = "\n".join(story_lines).strip()
        # Fallback scenes if the model didn't write them
        if not scenes:
            scenes = [
                f"A brave child hero in a magical {theme} adventure",
                f"Exciting moment in a colorful {theme} world",
                f"Happy ending celebration in a fantasy {theme} land",
            ]

        return {"story": story_text, "scenes": scenes[:3]}

    except (CapabilityNotSupportedError, ProviderAuthError, RateLimitError, AIProviderError) as e:
        print(f"❌ [StoryMaker] Provider error ({getattr(e, 'provider', 'unknown')}): {e}")
        return {"story": None, "scenes": []}
    except Exception as e:
        print(f"❌ [StoryMaker] LLM error: {e}")
        return {"story": None, "scenes": []}


# ── Main entry point ─────────────────────────────────────────────
def make_story(theme: str, characters: str = "") -> dict:
    """
    Main function. Returns:
    {
      "story": "...",
      "images": ["/path/img1.jpg", "/path/img2.jpg", "/path/img3.jpg"],
      "error": None | "..."
    }
    """
    from config import BASE_DIR
    output_dir = os.path.join(BASE_DIR, "outputs")
    os.makedirs(output_dir, exist_ok=True)

    print(f"📖 [StoryMaker] Creating story: '{theme}'...")
    result = _generate_story_and_prompts(theme, characters)

    if not result["story"]:
        return {"story": None, "images": [], "error": t("skills.story_maker.fail")}

    print(f"🎨 [StoryMaker] Creating {len(result['scenes'])} images...")
    images = []
    for i, scene_prompt in enumerate(result["scenes"], start=1):
        print(f"  → Image {i}: {scene_prompt[:60]}...")
        path = _generate_image(scene_prompt, output_dir, i)
        if path:
            images.append(path)
        time.sleep(1)  # short pause between requests

    return {
        "story": result["story"],
        "images": images,
        "error": None
    }
