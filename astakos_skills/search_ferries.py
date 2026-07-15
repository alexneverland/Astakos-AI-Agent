# ================================================================
# Project: Astakos AI Agent 🦞
# astakos_skills/search_ferries.py ← Ferry route search
# ================================================================

from langchain_community.tools import DuckDuckGoSearchRun

_search = DuckDuckGoSearchRun()

def search_ferries(origin: str, destination: str, date: str) -> str:
    """
    Searches for ferry routes and prices.
    origin: Departure port (e.g. 'Thessaloniki', 'Volos')
    destination: Destination (e.g. 'Skiathos', 'Mykonos')
    date: Travel date (e.g. '10 August 2026')
    """
    query = f"{origin} {destination} ferry schedule price {date}"
    print(f"\033[94m[Ferries]: Search: {query}\033[0m")
    
    try:
        results = _search.run(query)
        if not results:
            return t("skills.search_ferries.msg_no_results", org=origin, dest=destination, date=date)
        
        # Second search for official sites
        query2 = f"site:ferries.gr OR site:openseas.gr OR site:gtp.gr {origin} {destination} {date}"
        results2 = _search.run(query2)
        
        output = t("skills.search_ferries.msg_results_title", org=origin, dest=destination, date=date)
        output += results[:2000]
        if results2:
            output += t("skills.search_ferries.msg_official_sites", res=results2[:1000])
        
        return output
        
    except Exception as e:
        return t("skills.search_ferries.msg_error", e=str(e))


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 4:
        result = search_ferries(
            origin=sys.argv[1],
            destination=sys.argv[2],
            date=sys.argv[3],
        )
        print(result)
    else:
        print("Usage: python search_ferries.py [origin] [destination] [date]")
        print("e.g.: python search_ferries.py Thessaloniki Skiathos '10 August 2026'")
