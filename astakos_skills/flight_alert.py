import json
import os
from search_flights import search_flights

STATE_FILE = r'C:\astakos_v2\astakos_skills\flight_alert_state.json'

def run_alert():
    # Τρέχουσες ρυθμίσεις
    departure = "SKG"
    arrival = "KUT"
    start = "2026-08-09"
    end = "2026-08-14"
    threshold = 80  # Ειδοποίηση αν πέσει κάτω από 80€
    
    print(f"Checking flights for {departure}->{arrival} ({start} to {end})...")
    
    # Εκτέλεση αναζήτησης
    result_text = search_flights.invoke({
        "departure_id": departure,
        "arrival_id": arrival,
        "start_date": start,
        "end_date": end
    })
    
    # Φόρτωση αποτελεσμάτων από το json που παράγει το search_flights
    results_path = r'C:\astakos_v2\astakos_skills\flight_results.json'
    if not os.path.exists(results_path):
        print("No results found.")
        return

    with open(results_path, 'r', encoding='utf-8') as f:
        flights = json.load(f)
    
    if not flights:
        print("No flights found in JSON.")
        return

    # Εύρεση φθηνότερης
    cheapest = min(flights, key=lambda x: x.get("price", 9999))
    current_min_price = cheapest.get("price")
    current_min_date = cheapest.get("search_date")
    
    # Φόρτωση προηγούμενης κατάστασης
    last_price = 9999
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            state = json.load(f)
            last_price = state.get("last_price", 9999)
    
    print(f"Current cheapest: {current_min_price}€ on {current_min_date}")
    
    # Έλεγχος για ειδοποίηση
    alert_triggered = False
    message = ""
    
    if current_min_price < last_price:
        alert_triggered = True
        message = f"🚨 ΠΤΩΣΗ ΤΙΜΗΣ! Η φθηνότερη πτήση για Κουτάισι έπεσε στα {current_min_price}€ ({current_min_date})."
    elif current_min_price <= threshold:
        alert_triggered = True
        message = f"🎯 ΣΤΟΧΟΣ ΕΠΕΤΕΥΧΘΗ! Βρέθηκε πτήση με {current_min_price}€ στις {current_min_date}."
    
    # Ενημέρωση κατάστασης
    with open(STATE_FILE, 'w') as f:
        json.dump({"last_price": current_min_price, "last_date": current_min_date, "check_time": str(os.times())}, f)
    
    if alert_triggered:
        print(f"ALERT: {message}")
        # Εδώ θα μπορούσαμε να στείλουμε και Messenger αν είχαμε το session έτοιμο
        return message
    else:
        print("No price drop detected.")
        return None

if __name__ == "__main__":
    msg = run_alert()
    if msg:
        print(msg)
