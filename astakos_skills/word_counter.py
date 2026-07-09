import argparse
import string
from typing import Dict

def clean_text(text: str) -> str:
    """
    Καθαρίζει το κείμενο από σημεία στίξης και το μετατρέπει σε πεζά.
    
    Args:
        text (str): Το αρχικό κείμενο.
        
    Returns:
        str: Το καθαρισμένο κείμενο.
    """
    translator = str.maketrans('', '', string.punctuation)
    return text.translate(translator).lower()

def count_words(text: str) -> int:
    """
    Μετράει το συνολικό αριθμό λέξεων στο κείμενο.
    
    Args:
        text (str): Το κείμενο προς ανάλυση.
        
    Returns:
        int: Ο αριθμός των λέξεων.
    """
    if not text.strip():
        return 0
    cleaned_text = clean_text(text)
    words = cleaned_text.split()
    return len(words)

def get_word_frequencies(text: str) -> Dict[str, int]:
    """
    Υπολογίζει τη συχνότητα εμφάνισης κάθε λέξης στο κείμενο.
    
    Args:
        text (str): Το κείμενο προς ανάλυση.
        
    Returns:
        Dict[str, int]: Λεξικό με τις λέξεις και τη συχνότητά τους.
    """
    cleaned_text = clean_text(text)
    words = cleaned_text.split()
    
    frequencies: Dict[str, int] = {}
    for word in words:
        frequencies[word] = frequencies.get(word, 0) + 1
        
    return frequencies

def main() -> None:
    """
    Κύρια συνάρτηση εκτέλεσης του script μέσω CLI.
    """
    parser = argparse.ArgumentParser(description="Επαγγελματικό script καταμέτρησης λέξεων.")
    parser.add_argument("text", type=str, help="Το κείμενο που θέλετε να αναλύσετε")
    parser.add_argument("--freq", action="store_true", help="Εμφάνιση συχνότητας λέξεων")
    
    args = parser.parse_args()
    
    total_words = count_words(args.text)
    print(f"Συνολικές λέξεις: {total_words}")
    
    if args.freq:
        frequencies = get_word_frequencies(args.text)
        print("\nΣυχνότητα Λέξεων:")
        # Ταξινόμηση κατά φθίνουσα σειρά συχνότητας
        for word, count in sorted(frequencies.items(), key=lambda item: item[1], reverse=True):
            print(f"{word}: {count}")

if __name__ == "__main__":
    main()
