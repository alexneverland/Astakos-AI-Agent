import json
from astakos_skills import recipe_library

def test_save_preserves_two_recipes_with_same_name(monkeypatch, tmp_path):
    monkeypatch.setattr(recipe_library, "LIBRARY_FILE", tmp_path / "recipe_library.json")
    
    recipe1 = recipe_library.save_generated_recipe("carbonara", "recipe 1")
    recipe2 = recipe_library.save_generated_recipe("carbonara", "recipe 2")
    
    assert recipe1["id"] != recipe2["id"]
    assert recipe1["name"] == "carbonara"
    assert recipe2["name"] == "carbonara"
    
    data = recipe_library._load_library()
    assert len(data["recipes"]) == 2

def test_search_returns_matching_id(monkeypatch, tmp_path):
    monkeypatch.setattr(recipe_library, "LIBRARY_FILE", tmp_path / "recipe_library.json")
    
    recipe = recipe_library.save_generated_recipe("spaghetti carbonara", "content")
    recipe_library.save_generated_recipe("chicken soup", "content")
    
    result = json.loads(recipe_library.search_recipe_library.invoke({"query": "carbonara"}))
    assert len(result) == 1
    assert result[0]["id"] == recipe["id"]

def test_get_returns_exact_stored_content(monkeypatch, tmp_path):
    monkeypatch.setattr(recipe_library, "LIBRARY_FILE", tmp_path / "recipe_library.json")
    
    recipe = recipe_library.save_generated_recipe("pasta", "my pasta recipe")
    
    result = json.loads(recipe_library.get_saved_recipe.invoke({"recipe_id": recipe["id"]}))
    assert result["content"] == "my pasta recipe"
    assert result["name"] == "pasta"

def test_favorite_updates_only_requested_id(monkeypatch, tmp_path):
    monkeypatch.setattr(recipe_library, "LIBRARY_FILE", tmp_path / "recipe_library.json")
    
    recipe1 = recipe_library.save_generated_recipe("recipe 1", "content 1")
    recipe2 = recipe_library.save_generated_recipe("recipe 2", "content 2")
    
    recipe_library.mark_recipe_favorite.invoke({"recipe_id": recipe1["id"], "favorite": True})
    
    data = recipe_library._load_library()
    r1 = next(r for r in data["recipes"] if r["id"] == recipe1["id"])
    r2 = next(r for r in data["recipes"] if r["id"] == recipe2["id"])
    
    
    assert r1["is_favorite"] is True
    assert r2["is_favorite"] is False

def test_search_handles_punctuation_and_natural_language(monkeypatch, tmp_path):
    monkeypatch.setattr(recipe_library, "LIBRARY_FILE", tmp_path / "recipe_library.json")
    
    recipe = recipe_library.save_generated_recipe("κοτόπουλο λεμονάτο", "συνταγή")
    
    result = json.loads(recipe_library.search_recipe_library.invoke({"query": "Τι είχαμε κάνει για κοτόπουλο;"}))
    assert len(result) == 1
    assert result[0]["id"] == recipe["id"]
