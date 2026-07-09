import pytest
from astakos_skills.word_counter import clean_text, count_words, get_word_frequencies

def test_clean_text():
    assert clean_text("Hello, World!") == "hello world"
    assert clean_text("Test... 123?") == "test 123"
    assert clean_text("NO PUNCTUATION") == "no punctuation"

def test_count_words():
    assert count_words("This is a test") == 4
    assert count_words("   Spaces   everywhere  ") == 2
    assert count_words("") == 0
    assert count_words("One-word") == 1 # "Oneword"

def test_get_word_frequencies():
    text = "Hello world! Hello everyone."
    freqs = get_word_frequencies(text)
    assert freqs["hello"] == 2
    assert freqs["world"] == 1
    assert freqs["everyone"] == 1
    
    assert get_word_frequencies("   ") == {}
