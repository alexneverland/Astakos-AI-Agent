import argparse
import string
from typing import Dict

def clean_text(text: str) -> str:
    """
    Cleans the text from punctuation and converts it to lowercase.
    
    Args:
        text (str): The original text.
        
    Returns:
        str: The cleaned text.
    """
    translator = str.maketrans('', '', string.punctuation)
    return text.translate(translator).lower()

def count_words(text: str) -> int:
    """
    Counts the total number of words in the text.
    
    Args:
        text (str): The text to be analyzed.
        
    Returns:
        int: The number of words.
    """
    if not text.strip():
        return 0
    cleaned_text = clean_text(text)
    words = cleaned_text.split()
    return len(words)

def get_word_frequencies(text: str) -> Dict[str, int]:
    """
    Calculates the frequency of occurrence of each word in the text.
    
    Args:
        text (str): The text to analyze.
        
    Returns:
        Dict[str, int]: A dictionary with the words and their frequency.
    """
    cleaned_text = clean_text(text)
    words = cleaned_text.split()
    
    frequencies: Dict[str, int] = {}
    for word in words:
        frequencies[word] = frequencies.get(word, 0) + 1
        
    return frequencies

def main() -> None:
    """
    Main function for executing the script via CLI.
    """
    parser = argparse.ArgumentParser(description="Professional word counting script.")
    parser.add_argument("text", type=str, help=t("skills.word_counter.msg_help_text"))
    parser.add_argument("--freq", action="store_true", help="Show word frequency")
    
    args = parser.parse_args()
    
    total_words = count_words(args.text)
    print(f"Total words: {total_words}")
    
    if args.freq:
        frequencies = get_word_frequencies(args.text)
        print("\nWord frequency:")
        # Sort in descending order of frequency
        for word, count in sorted(frequencies.items(), key=lambda item: item[1], reverse=True):
            print(f"{word}: {count}")

if __name__ == "__main__":
    main()
