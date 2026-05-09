# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: Lazaros (Piston-7)
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

def calculate_shopping_cost(products_string: str) -> float:
    total_cost = 0.0
    products = products_string.split(',')
    for product_info in products:
        try:
            name, price_str = product_info.strip().split(':')
            price = float(price_str)
            total_cost += price
        except ValueError:
            print(f"Skipping invalid product entry: {product_info}. Please ensure format is 'item:price'.")
            continue
    
    # Add 10% for unforeseen expenses
    final_cost = total_cost * 1.10
    return final_cost

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        products_input = sys.argv[1]
        cost = calculate_shopping_cost(products_input)
        print(f"Το εκτιμώμενο συνολικό κόστος αγορών είναι: {cost:.2f} ευρώ.")
    else:
        print("Παρακαλώ δώστε μια λίστα προϊόντων και τιμών. Παράδειγμα: 'ντομάτες:2.5, πατάτες:1.8'")
