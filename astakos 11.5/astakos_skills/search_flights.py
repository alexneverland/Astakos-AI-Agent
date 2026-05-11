import requests
import os
import json
from datetime import datetime, timedelta
from langchain_core.tools import tool

@tool
def search_flights(departure_id: str, arrival_id: str, start_date: str, end_date: str, return_date: str = None):
    """
    Αναζητά πτήσεις μέσω SerpApi (Google Flights) για ένα εύρος ημερομηνιών.
    Args:
        departure_id: Κωδικός αεροδρομίου (π.χ. 'SKG')
        arrival_id: Κωδικός αεροδρομίου (π.χ. 'LON')
        start_date: Ημερομηνία έναρξης (YYYY-MM-DD)
        end_date: Ημερομηνία λήξης (YYYY-MM-DD)
        return_date: Ημερομηνία επιστροφής (YYYY-MM-DD) - Προαιρετικό
    """
    env_path = r'C:\astakos_v2\.env'
    api_key = None
    
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                if 'SERPAPI_KEY=' in line:
                    api_key = line.split('=')[1].strip().strip("'").strip('"')
                    break

    if not api_key:
        return "Σφάλμα: Δεν βρέθηκε το SERPAPI_KEY στο .env"

    try:
        d_start = datetime.strptime(start_date, "%Y-%m-%d")
        d_end = datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError:
        return "Σφάλμα: Οι ημερομηνίες πρέπει να είναι σε μορφή YYYY-MM-DD."

    all_results = []
    current_date = d_start
    
    while current_date <= d_end:
        date_str = current_date.strftime("%Y-%m-%d")
        params = {
            "engine": "google_flights",
            "departure_id": departure_id,
            "arrival_id": arrival_id,
            "outbound_date": date_str,
            "currency": "EUR",
            "hl": "el",
            "api_key": api_key,
            "type": "2" if not return_date else "1"
        }
        if return_date:
            params["return_date"] = return_date

        try:
            response = requests.get("https://serpapi.com/search.json", params=params, timeout=15)
            data = response.json()
            
            if "error" not in data:
                flights = data.get("best_flights", []) or data.get("other_flights", [])
                for f in flights:
                    f["search_date"] = date_str # Προσθήκη ημερομηνίας αναζήτησης στο αποτέλεσμα
                all_results.extend(flights)
            
        except Exception as e:
            print(f"Σφάλμα στην ημερομηνία {date_str}: {str(e)}")
        
        current_date += timedelta(days=1)

    # Αποθήκευση σε log file
    log_path = r'C:\astakos_v2\astakos_skills\flight_results.json'
    with open(log_path, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=4)

    if not all_results:
        return "Δεν βρέθηκαν πτήσεις για το επιλεγμένο διάστημα."

    # Συνοπτική απάντηση
    output = f"✅ Η αναζήτηση ολοκληρώθηκε για το διάστημα {start_date} έως {end_date}.\n"
    output += f"Συνολικά βρέθηκαν {len(all_results)} επιλογές. Τα πλήρη δεδομένα αποθηκεύτηκαν στο `flight_results.json`.\n\n"
    
    # Εμφάνιση των 3 φθηνότερων
    sorted_flights = sorted([f for f in all_results if f.get("price")], key=lambda x: x.get("price"))
    output += "✈️ **Οι 3 φθηνότερες επιλογές:**\n"
    for i, flight in enumerate(sorted_flights[:3], 1):
        price = flight.get("price")
        date = flight.get("search_date")
        airline = flight.get("flights", [{}])[0].get("airline", "N/A")
        output += f"{i}. {date}: **{airline}** - {price}€\n"
        
    return output
