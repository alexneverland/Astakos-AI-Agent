import os
import requests
from dotenv import load_dotenv
from langchain_core.tools import tool
from core.i18n import t

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
        return t("skills.search_flights.no_key")

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
            trip_type = t("skills.search_flights.msg_trip_round", date=return_date)
        else:
            params["type"] = "2"
            trip_type = t("skills.search_flights.msg_trip_one_way")

        final_output.append(t("skills.search_flights.msg_flight_search", origin=origin, destination=destination, date=date, trip_type=trip_type))
        
        try:
            response = requests.get("https://serpapi.com/search", params=params)
            if response.status_code != 200:
                final_output.append(t("skills.search_flights.msg_flight_error", e=response.text))
                continue

            data = response.json()
            all_flights = data.get("best_flights", []) + data.get("other_flights", [])
            
            if not all_flights:
                final_output.append(t("skills.search_flights.no_flights"))
                continue

            for idx, flight in enumerate(all_flights[:3]): # We fetch the 3 cheapest
                flights_info = flight.get("flights", [{}])[0]
                airline = flights_info.get("airline", t("skills.search_flights.airline_unknown"))
                price = flight.get("price", t("skills.search_flights.airline_unknown"))
                departure_time = flights_info.get("departure_airport", {}).get("time", "")
                arrival_time = flights_info.get("arrival_airport", {}).get("time", "")
                
                final_output.append(t("skills.search_flights.msg_flight_result", idx=idx+1, airline=airline, price=price, dep=departure_time, arr=arrival_time))
            final_output.append("") # Empty line for separation
                
        except Exception as e:
            final_output.append(t("skills.search_flights.msg_network_error", e=e))

    final_output.append("-" * 50)
    
    # We return the text to the Agent instead of simply printing it
    return "\n".join(final_output)