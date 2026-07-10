import os
import requests
from dotenv import load_dotenv
from langchain_core.tools import tool

# Load key
load_dotenv()
SERPAPI_KEY = os.environ.get("SERPAPI_KEY")

@tool
def search_flights(origin: str, destination: str, dates: str, return_date: str) -> str:
    """
    Searches for real flights and returns prices.
    
    USAGE RULES (DO NOT violate them):
    1. origin & destination: ONLY capitalized IATA codes (e.g., SKG, KUT).
    2. dates: Departure dates (e.g., "2026-08-09,2026-08-10").
    3. return_date: Return date (e.g., "2026-08-15"). If it is a one-way trip, STRICTLY use the word "None".
    """
    if not SERPAPI_KEY:
        return "❌ Σφάλμα: Δεν βρέθηκε το SERPAPI_KEY στο .env"

    # We split the dates
    dates_list = [d.strip() for d in dates.split(",")]
    
    final_output = []
    final_output.append("-" * 50)
    
    for date in dates_list:
        params = {
            "engine": "google_flights",
            "departure_id": origin,
            "arrival_id": destination,
            "outbound_date": date, 
            "currency": "EUR",
            "hl": "el",
            "api_key": SERPAPI_KEY
        }

        # [MASTRO-FIX]: We check if they sent us the word "None"
        if return_date and return_date.lower() != "none":
            params["type"] = "1"
            params["return_date"] = return_date
            trip_type = f"με Επιστροφή: {return_date}"
        else:
            params["type"] = "2"
            trip_type = "Απλή Μετάβαση"

        final_output.append(f"✈️ [Αναζήτηση]: {origin} -> {destination} | Αναχώρηση: {date} | {trip_type}")
        
        try:
            response = requests.get("https://serpapi.com/search", params=params)
            if response.status_code != 200:
                final_output.append(f"❌ Σφάλμα API: {response.text}\n")
                continue

            data = response.json()
            all_flights = data.get("best_flights", []) + data.get("other_flights", [])
            
            if not all_flights:
                final_output.append("❌ Δεν βρέθηκαν πτήσεις.\n")
                continue

            for idx, flight in enumerate(all_flights[:3]): # We fetch the 3 cheapest
                flights_info = flight.get("flights", [{}])[0]
                airline = flights_info.get("airline", "Άγνωστη")
                price = flight.get("price", "Άγνωστη")
                departure_time = flights_info.get("departure_airport", {}).get("time", "")
                arrival_time = flights_info.get("arrival_airport", {}).get("time", "")
                
                final_output.append(f"  [{idx+1}] {airline} | 💶 Τιμή: {price}€ | Ώρες: {departure_time} - {arrival_time}")
            final_output.append("") # Empty line for separation
                
        except Exception as e:
            final_output.append(f"❌ Σφάλμα δικτύου: {e}\n")

    final_output.append("-" * 50)
    
    # We return the text to the Agent instead of simply printing it
    return "\n".join(final_output)