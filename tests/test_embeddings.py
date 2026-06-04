"""
Tests για το embeddings layer.
Τρεξε ΠΡΙΝ και ΜΕΤΑ οποιαδηποτε αλλαγη στο services/embeddings.py
για να επαληθευσεις οτι η semantic search δεν σπασε.

Απαιτει live Vertex AI connection.
Τρεξε με: python -m pytest tests/test_embeddings.py -v -m integration
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import math
import pytest

pytestmark = pytest.mark.integration  # Ολα τα tests εδω απαιτουν live Vertex AI


def cosine_similarity(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x**2 for x in a))
    mag_b = math.sqrt(sum(x**2 for x in b))
    return dot / (mag_a * mag_b) if mag_a and mag_b else 0.0


@pytest.fixture(scope="module")
def embeddings():
    from services.embeddings import embeddings
    return embeddings


def test_embed_query_returns_vector(embeddings):
    vec = embeddings.embed_query("Αστακός AI agent")
    assert isinstance(vec, list)
    assert len(vec) > 0
    assert all(isinstance(x, float) for x in vec)


def test_embed_query_dimensions(embeddings):
    """text-embedding-004 παραγει 768-dimensional vectors."""
    vec = embeddings.embed_query("test")
    assert len(vec) == 768


def test_similar_phrases_high_similarity(embeddings):
    """Παρομοιες φρασεις → similarity > 0.8."""
    v1 = embeddings.embed_query("ο Αλεξανδρος παει σχολειο")
    v2 = embeddings.embed_query("ο Αλεξανδρος εχει σχολειο σημερα")
    sim = cosine_similarity(v1, v2)
    print(f"\nSimilarity (similar): {sim:.4f}")
    assert sim > 0.8


def test_unrelated_phrases_low_similarity(embeddings):
    """Άσχετες φρασεις → similarity < 0.6."""
    v1 = embeddings.embed_query("ο Αλεξανδρος παει σχολειο")
    v2 = embeddings.embed_query("git push origin main")
    sim = cosine_similarity(v1, v2)
    print(f"\nSimilarity (unrelated): {sim:.4f}")
    assert sim < 0.6


def test_cache_returns_same_vector(embeddings):
    """Το ίδιο query επιστρεφει ακριβως το ίδιο vector (cache hit)."""
    v1 = embeddings.embed_query("cache test phrase 12345")
    v2 = embeddings.embed_query("cache test phrase 12345")
    assert v1 == v2


def test_embed_documents_returns_list(embeddings):
    docs = ["Αστακός agent", "routine learning", "memory scoring"]
    vecs = embeddings.embed_documents(docs)
    assert len(vecs) == 3
    assert all(len(v) == 768 for v in vecs)
