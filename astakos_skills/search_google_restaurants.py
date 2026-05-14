@tool
def search_google_restaurants(query: str, location: str = "Thessaloniki") -> str:
    """
    Αναζητά εστιατόρια μέσω Google Search με βαθμολογίες.
    """
    from playwright.sync_api import sync_playwright
    
    # URL encoded query
    search_query = f"{query} restaurants in {location}".replace(" ", "+")
    search_url = f"https://www.google.com/search?q={search_query}"
    
    try:
        with sync_playwright() as p:
            # Χρήση του Firefox ή Chrome με πιο "ανθρώπινα" headers
            browser = p.firefox.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0"
            )
            page = context.new_page()
            
            page.goto(search_url)
            
            # Αναμονή για τα αποτελέσματα (Local Pack)
            try:
                page.wait_for_selector('div[jscontroller]', timeout=5000)
            except:
                pass # Αν δεν φορτώσει το local pack, ίσως βρούμε απλά αποτελέσματα

            # Εξαγωγή ονομάτων
            listings = page.locator('h3').all()
            found_places = []
            for item in listings:
                try:
                    name = item.inner_text().strip()
                    if len(name) > 2 and name not in ["Αποτελέσματα αναζήτησης", "Web results", "Περισσότερα"]:
                        found_places.append(f"🍴 {name}")
                except:
                    continue
            
            browser.close()
            
            # Φιλτράρισμα αποτελεσμάτων (κρατάμε τα 5 πρώτα μοναδικά)
            unique_places = list(dict.fromkeys(found_places))[:5]
            
            if not unique_places:
                return "❌ Δεν βρέθηκαν αποτελέσματα. Το Google ίσως μπλόκαρε το request."

            return "🔍 Google Local Results:\n\n" + "\n".join(unique_places)
            
    except Exception as e:
        return f"❌ Search Error: {str(e)}"
