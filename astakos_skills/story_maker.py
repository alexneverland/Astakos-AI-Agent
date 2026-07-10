# ================================================================
# Project: Astakos AI Agent 🦞
# Skill: Story Maker for Alexander
# Generates a fairy tale + 3 scene images via Pollinations.ai
# ================================================================

import os
import re
import time
import json
import requests

# ── Pollinations image generator ────────────────────────────────
def _generate_image(prompt: str, output_dir: str, index: int) -> str | None:
    """Creates an image. Returns the path, or None if it fails."""
    try:
        # Children's style: drawing, vibrant colors, happy
        styled = (
            f"{prompt}, children's book illustration, watercolor, "
            f"colorful, cute, magical, soft lighting, 6 year old friendly, "
            f"no text, no letters"
        )
        url = (
            f"https://image.pollinations.ai/prompt/{requests.utils.quote(styled)}"
            f"?nologo=true&model=flux&width=1024&height=1024&seed={index * 999}"
        )
        res = requests.get(url, timeout=45)
        if res.status_code == 200 and "image" in res.headers.get("Content-Type", ""):
            fname = os.path.join(output_dir, f"story_img_{index}_{int(time.time())}.jpg")
            with open(fname, "wb") as f:
                f.write(res.content)
            return fname
    except Exception as e:
        print(f"⚠️ [StoryMaker] Εικόνα {index} απέτυχε: {e}")
    return None


# ── LLM story + scene prompts ────────────────────────────────────
def _generate_story_and_prompts(theme: str, characters: str = "") -> dict:
    """Calls Gemini for a fairy tale + 3 image prompts."""
    try:
        import vertexai
        from vertexai.generative_models import GenerativeModel
        from core.brain import FAST_MODEL as MAIN_MODEL

        vertexai.init(
            project=os.getenv("PROJECT_ID", "astakos-finall"),
            location=os.getenv("LOCATION", "global")
        )
        model = GenerativeModel(MAIN_MODEL)

        char_hint = f" Κύριοι χαρακτήρες: {characters}." if characters else ""
        system_prompt = f"""Είσαι ένας δημιουργικός συγγραφέας παιδικών παραμυθιών.
Γράφεις ΓΙΑ παιδί 6 ετών που λέγεται Αλέξανδρος.
Χρησιμοποιείς απλή γλώσσα, χαρούμενο τόνο, ηθικό μάθημα στο τέλος.
Το παραμύθι να έχει αρχή-μέση-τέλος, ~500 λέξεις.{char_hint}

ΣΗΜΑΝΤΙΚΟ: Στο τέλος, γράψε ακριβώς 3 γραμμές με prefixes:
SCENE1: [σύντομη αγγλική περιγραφή σκηνής για εικόνα]
SCENE2: [σύντομη αγγλική περιγραφή σκηνής για εικόνα]
SCENE3: [σύντομη αγγλική περιγραφή σκηνής για εικόνα]
Κάθε SCENE να είναι μία πρόταση στα αγγλικά, συγκεκριμένη και ζωντανή."""

        response = model.generate_content(
            f"Θέμα παραμυθιού: {theme}\n\n{system_prompt}"
        )
        raw = response.text.strip()

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

    print(f"📖 [StoryMaker] Δημιουργία παραμυθιού: '{theme}'...")
    result = _generate_story_and_prompts(theme, characters)

    if not result["story"]:
        return {"story": None, "images": [], "error": "Αποτυχία δημιουργίας παραμυθιού"}

    print(f"🎨 [StoryMaker] Δημιουργία {len(result['scenes'])} εικόνων...")
    images = []
    for i, scene_prompt in enumerate(result["scenes"], start=1):
        print(f"  → Εικόνα {i}: {scene_prompt[:60]}...")
        path = _generate_image(scene_prompt, output_dir, i)
        if path:
            images.append(path)
        time.sleep(1)  # short pause between requests

    return {
        "story": result["story"],
        "images": images,
        "error": None
    }
