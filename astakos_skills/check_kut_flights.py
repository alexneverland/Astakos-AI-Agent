from search_flights import search_flights

# Αναζήτηση για SKG-KUT από 9 έως 14 Αυγούστου
result = search_flights.invoke({
    "departure_id": "SKG",
    "arrival_id": "KUT",
    "start_date": "2026-08-09",
    "end_date": "2026-08-14"
})

print(result)
