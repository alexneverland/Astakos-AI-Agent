from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE_PROMPTS = ROOT / "core" / "prompts.md"
RECIPE_PROMPT = ROOT / "prompts" / "recipe_expert.md"


def test_named_source_recipe_requests_route_to_web_agent():
    prompt = CORE_PROMPTS.read_text(encoding="utf-8")

    assert "named external source" in prompt
    assert "route to Web_Agent instead of Home_Agent" in prompt
    assert "[NAMED RECIPE SOURCE - CRITICAL]" in prompt
    assert "duckduckgo_search" in prompt
    assert "browse_url" in prompt


def test_recipe_expert_does_not_claim_an_unverified_external_source():
    prompt = RECIPE_PROMPT.read_text(encoding="utf-8")

    assert "no verified external source" in prompt
    assert "Never claim" in prompt
