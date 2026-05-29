import os
import ctypes
import requests
from dotenv import load_dotenv

def check_flights():
    load_dotenv()
    SERPAPI_KEY = os.environ.get("SERPAPI_KEY")
    if not SERPAPI_KEY:
        return
    
    origin = "SKG"
    destination = "KUT"
    dates = ["2026-08-07", "2026-08-09", "2026-08-10"]
    
    alerts = []
    
    for date in dates:
        params = {
            "engine": "google_flights",
            "departure_id": origin,
            "arrival_id": destination,
            "outbound_date": date, 
            "currency": "EUR",
            "hl": "el",
            "api_key": SERPAPI_KEY,
            "type": "2"
        }
        
        try:
            response = requests.get("https://serpapi.com/search", params=params)
            if response.status_code == 200:
                data = response.json()
                all_flights = data.get("best_flights", []) + data.get("other_flights", [])
                
                for flight in all_flights:
                    price = flight.get("price")
                    if price and isinstance(price, (int, float)) and price < 100:
                        flights_info = flight.get("flights", [{}])[0]
                        airline = flights_info.get("airline", "Άγνωστη")
                        alerts.append(f"{date}: {airline} με {price}€")
                        break
        except Exception:
            pass
            
    if alerts:
        msg = "Βρέθηκαν φθηνές πτήσεις SKG-KUT κάτω από 100€!\n\n" + "\n".join(alerts)
        ctypes.windll.user32.MessageBoxW(0, msg, "Ειδοποίηση Πτήσεων", 0x40 | 0x1)

if __name__ == "__main__":
    check_flights()
