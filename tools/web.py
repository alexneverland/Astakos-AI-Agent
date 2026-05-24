# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: Lazaros (Piston-7)
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

import os
import re
import json
import urllib.parse
import unicodedata
import requests
import xml.etree.ElementTree as ET
from langchain_core.tools import tool
from typing import Annotated
from playwright.sync_api import sync_playwright
try:
    from playwright_stealth import stealth_sync
except ImportError:
    # [MASTRO-FIX]: Σε κάποιες εκδόσεις η συνάρτηση λέγεται σκέτο 'stealth'
    try:
        from playwright_stealth import stealth as stealth_sync
    except ImportError:
        print("⚠️ [Web Tool]: Δεν βρέθηκε το stealth_sync. Θα συνεχίσω χωρίς stealth mode.")
        stealth_sync = None

def remove_accents(input_str: str) -> str:
    """Αφαιρεί τόνους και μετατρέπει σε πεζά."""
    if not isinstance(input_str, str):
        return ""
    nfkd_form = unicodedata.normalize('NFKD', input_str)
    return u"".join([c for c in nfkd_form if not unicodedata.combining(c)]).lower()

@tool
def relay_local_payload(target_entity: str, payload_data: str) -> str:
    """
    Αποθηκεύει ένα προσχέδιο μηνύματος Messenger (Facebook).
    Χρησιμοποίησέ το ΟΤΑΝ προτείνεις στον χρήστη να στείλει ένα μήνυμα, 
    πριν πάρεις την τελική του έγκριση.
    """
    import os
    import json
    base_dir = os.path.dirname(os.path.abspath(__file__))
    draft_file = os.path.join(base_dir, "..", "messenger_draft.json")
    
    # [MASTRO-FIX]: Τα κλειδιά του JSON παίρνουν τις σωστές μεταβλητές!
    draft_data = {
        "target_name": target_entity, 
        "message": payload_data
    }
    
    with open(draft_file, "w", encoding="utf-8") as f:
        json.dump(draft_data, f, ensure_ascii=False, indent=4)
        
    return f"✅ Το προσχέδιο για '{target_entity}' αποθηκεύτηκε. Ρώτα τον Λάζαρο: 'Να το στείλω;'."
@tool
def get_news(topic: str = "Γενικά", limit: int = 15) -> str:
    """Φέρνει τίτλους ειδήσεων από το Google News."""
    try:
        print(f"\033[96m[Web]: Ανάκτηση ειδήσεων για: {topic}...\033[0m")
        url = (
            "https://news.google.com/rss?hl=el&gl=GR&ceid=GR:el"
            if topic.lower() in ["γενικά", "general", ""]
            else f"https://news.google.com/rss/search?q={urllib.parse.quote(topic)}&hl=el&gl=GR&ceid=GR:el"
        )
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"}
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            items = ET.fromstring(response.text).findall(".//item")
            news = [f"{i + 1}. {item.find('title').text}" for i, item in enumerate(items[:limit])]
            return "\n".join(news) if news else "Δεν βρέθηκαν ειδήσεις."
        return f"Error: Status {response.status_code}"
    except Exception as e:
        return f"News Error: {str(e)}"


@tool
def get_weather_forecast(location: str, days: int = 14) -> str:
    """Επιστρέφει την αναλυτική πρόγνωση καιρού για μια περιοχή (έως 16 ημέρες)."""
    try:
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={location}&count=1&language=el&format=json"
        geo_resp = requests.get(geo_url, timeout=10).json()

        if "results" not in geo_resp or not geo_resp["results"]:
            return f"Δεν μπόρεσα να βρω την τοποθεσία: {location}"

        lat = geo_resp["results"][0]["latitude"]
        lon = geo_resp["results"][0]["longitude"]
        place_name = geo_resp["results"][0]["name"]

        weather_url = (
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
            f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum"
            f"&timezone=auto&forecast_days={days}"
        )
        weather_resp = requests.get(weather_url, timeout=10).json()

        daily = weather_resp.get("daily", {})
        if not daily:
            return "Δεν βρέθηκαν δεδομένα καιρού."

        dates = daily.get("time", [])
        t_max = daily.get("temperature_2m_max", [])
        t_min = daily.get("temperature_2m_min", [])
        precip = daily.get("precipitation_sum", [])

        result = f"Πρόγνωση καιρού για {place_name} ({days} ημέρες):\n"
        for i in range(len(dates)):
            rain_info = f"Βροχή: {precip[i]}mm" if precip[i] > 0 else "Χωρίς βροχή"
            result += f"- {dates[i]}: Max {t_max[i]}°C, Min {t_min[i]}°C, {rain_info}\n"

        return result
    except Exception as e:
        return f"Σφάλμα καιρού: {str(e)}"


@tool
def search_supermarket_offers(query: Annotated[str, "Το προϊόν που ψάχνουμε, π.χ. 'φακές'"]) -> str:
    """Αναζητά τις 5 φθηνότερες τιμές για ένα προϊόν στο e-Katanalotis."""
    url = "https://warply.s3.amazonaws.com/applications/ed840ad545884deeb6c6b699176797ed/basket-retailers/prices.json?cid=1777896000000"
    headers = {
        'sec-ch-ua-platform': '"Windows"',
        'Referer': 'https://e-katanalotis.gov.gr/',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/javascript, */*; q=0.01',
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            return f"Σφάλμα σύνδεσης (Status: {response.status_code})"

        data = response.json()
        merchants_dict = {}
        items_list = []

        try:
            result_data = data.get("context", {}).get("MAPP_PRODUCTS", {}).get("result", {})
            for m in result_data.get("merchants", []):
                merchants_dict[m.get("merchant_uuid")] = m.get("display_name") or m.get("name") or "Άγνωστο"
            items_list = result_data.get("products", [])
        except Exception:
            pass

        if not items_list:
            return "Σφάλμα: Δεν βρέθηκαν προϊόντα στο JSON."

        clean_query = remove_accents(query)
        found_items = []

        for item in items_list:
            if isinstance(item, dict):
                name = item.get('name') or item.get('product_name') or item.get('title') or ""
                clean_name = remove_accents(name)

                if clean_query in clean_name:
                    prices_data = item.get('prices', [])

                    if isinstance(prices_data, list) and len(prices_data) > 0:
                        for p_info in prices_data:
                            p_val = p_info.get('price')
                            muid = p_info.get('merchant_uuid')
                            try:
                                c_price = float(str(p_val).replace(',', '.'))
                            except:
                                continue
                            if c_price > 0:
                                shop = merchants_dict.get(muid) or 'Super Market'
                                found_items.append({'name': name, 'price': c_price, 'shop': shop})
                    else:
                        p_val = item.get('price') or 0
                        try:
                            c_price = float(str(p_val).replace(',', '.'))
                        except:
                            c_price = 0.0
                        if c_price > 0:
                            muid = item.get('merchant_uuid')
                            shop = merchants_dict.get(muid) or item.get('retailer_name') or 'Super Market'
                            found_items.append({'name': name, 'price': c_price, 'shop': shop})

        if not found_items:
            return f"Δεν βρέθηκαν έγκυρες τιμές για '{query}'."

        found_items.sort(key=lambda x: x['price'])
        top_5 = found_items[:5]

        res_msg = f"🛒 **Οι καλύτερες τιμές για '{query}':**\n"
        for i, itm in enumerate(top_5, 1):
            res_msg += f"{i}. {itm['name']} -> **{itm['price']}€** ({itm['shop']})\n"

        return res_msg

    except Exception as e:
        return f"Παρουσιάστηκε σφάλμα: {str(e)}"


@tool
def search_goldmall_offers(query: str) -> str:
    """Deep Scan σε ΟΛΕΣ τις προσφορές του Goldmall χωρίς περιορισμό."""
    search_term = "σινεμά" if any(x in query.lower() for x in ["σινεμά", "ταινία", "ταινιες"]) else query

    try:
        print(f"\n\033[94m[DEBUG]: Full Deep Scan for: '{search_term}'\033[0m")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
            page = context.new_page()

            target_url = f"https://www.goldmall.gr/search/term?search_term={search_term}"
            page.goto(target_url, timeout=30000)

            try:
                page.wait_for_selector(".deal-tile", timeout=10000)
            except:
                return f"Δεν βρέθηκαν αποτελέσματα για '{search_term}'."

            deals = page.locator(".deal-tile").all()
            results = []

            for i, deal in enumerate(deals):
                try:
                    title_text = deal.inner_text().strip().split('\n')[0]
                    link_el = deal.locator("a").first
                    relative_link = link_el.get_attribute("href")
                    full_link = f"https://www.goldmall.gr{relative_link}"

                    print(f"\033[94m[DEBUG]: Opening Offer {i+1}/{len(deals)}: {full_link}\033[0m")

                    detail_page = context.new_page()
                    detail_page.goto(full_link, timeout=15000, wait_until="domcontentloaded")

                    raw_text = ""
                    potential_selectors = [".offer-details", ".tab-content", ".description-container"]
                    for selector in potential_selectors:
                        element = detail_page.locator(selector).first
                        if element.is_visible(timeout=2000):
                            raw_text = element.inner_text()
                            break

                    if not raw_text:
                        raw_text = detail_page.locator("body").inner_text()

                    noise_words = ["newsletter", "όρους και τις προϋποθέσεις", "T:2310", "info@", "ΠΩΣ ΛΕΙΤΟΥΡΓΕΙ", "ΤΡΟΠΟΙ ΑΓΟΡΑΣ"]
                    lines = raw_text.split('\n')

                    schedule_info = []
                    for line in lines:
                        clean_line = line.strip()
                        if len(clean_line) > 5 and not any(noise in clean_line for noise in noise_words):
                            if any(char.isdigit() for char in clean_line) or any(
                                day in clean_line for day in ["Σάββατο", "Κυριακή", "Παρασκευή", "Πέμπτη"]
                            ):
                                schedule_info.append(clean_line)

                    detail_page.close()
                    description = " | ".join(schedule_info[:5])
                    results.append(f"🎬 **{title_text}**\n📅 {description if description else 'Δείτε το link για ώρες.'}")

                except Exception as e:
                    print(f"\033[91m[DEBUG]: Σφάλμα στην προσφορά {i}: {str(e)}\033[0m")
                    continue

            browser.close()
            return "🛒 **Πλήρεις Λεπτομέρειες Goldmall (Θεσσαλονίκη):**\n\n" + "\n\n---\n\n".join(results)

    except Exception as e:
        return f"Γενικό Σφάλμα Goldmall: {str(e)}"


@tool
def execute_local_pipeline(target_name: str = "", message: str = "") -> str:
    """Στέλνει μήνυμα στο Facebook Messenger. Αν δεν δοθούν ορίσματα, διαβάζει το έτοιμο προσχέδιο!"""
    import time
    import json
    import os
    from playwright.sync_api import sync_playwright

    base_dir = os.path.dirname(os.path.abspath(__file__))
    draft_file = os.path.join(base_dir, "..", "messenger_draft.json")

    # 1. [MASTRO INTERCEPTOR]: Έλεγχος JSON Buffer
    if not target_name or not message:
        if os.path.exists(draft_file):
            with open(draft_file, "r", encoding="utf-8") as f:
                draft = json.load(f)
                target_name = target_name or draft.get("target_name", "")
                message = message or draft.get("message", "")
            
            os.remove(draft_file)
            print(f"\033[93m[Messenger]: Βρέθηκε draft για {target_name}. Εκτέλεση...\033[0m")
        else:
            return "❌ Σφάλμα: Δεν βρέθηκε προσχέδιο!"

    # 2. [MASTRO FIX]: Aliases από το astakos_profile.json
    profile_path = os.path.join(base_dir, "..", "astakos_profile.json")
    aliases = {}
    if os.path.exists(profile_path):
        try:
            with open(profile_path, 'r', encoding='utf-8') as f:
                profile_data = json.load(f)
                aliases = profile_data.get("contacts", {})
        except Exception as e:
            print(f"⚠️ [Messenger Error]: {e}")

    aliases_lower = {k.lower(): v for k, v in aliases.items()}
    final_name = aliases_lower.get(target_name.strip().lower(), target_name)

    profile_dir = os.path.join(base_dir, "..", "astakos_skills", "messenger_profile")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch_persistent_context(
                user_data_dir=profile_dir,
                headless=False,
                args=['--disable-blink-features=AutomationControlled']
            )

            page = browser.new_page()
            page.goto("https://www.messenger.com/", wait_until="domcontentloaded", timeout=60000)

            # Εύρεση του Search Box
            search_box = page.locator('input[aria-label="Αναζήτηση στο Messenger"], input[aria-label="Search Messenger"], input[type="search"]').first
            search_box.wait_for(state="visible", timeout=10000)

            # --- [MASTRO-SEARCH-LOGIC]: Βελτιωμένη Αναζήτηση ---
            search_box.click()
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            time.sleep(0.5)
            
            # Πληκτρολόγηση με καθυστέρηση για να προλάβει το UI
            page.keyboard.type(final_name, delay=120)
            print(f"🔍 Αναζήτηση για: {final_name}...")

            # Περιμένουμε να εμφανιστούν τα αποτελέσματα - όχι sleep, αλλά wait για το πρώτο gridcell
            try:
                page.wait_for_selector('div[role="gridcell"]', timeout=8000)
            except:
                browser.close()
                return f"❌ Timeout: Δεν φορτώθηκαν αποτελέσματα για '{final_name}'."

            time.sleep(1)  # μικρό buffer μετά την εμφάνιση

            # Παίρνουμε ΟΛΑ τα gridcells και ψάχνουμε exact/partial match
            gridcells = page.locator('div[role="gridcell"]').all()
            target_cell = None

            for cell in gridcells:
                try:
                    cell_text = cell.inner_text().strip()
                    print(f"  → gridcell: '{cell_text}'")
                    if final_name.lower() in cell_text.lower():
                        target_cell = cell
                        break
                except:
                    continue

            if target_cell is None:
                browser.close()
                return f"❌ Δεν βρέθηκε η επαφή '{final_name}' στο Messenger."

            target_cell.click(force=True)
            print(f"✅ Επιλέχθηκε η επαφή: {final_name}")
            time.sleep(2.5)  # περιμένουμε να φορτώσει η συνομιλία
            # Αποστολή μηνύματος
            chat_box = page.locator('div[role="textbox"]').last
            chat_box.wait_for(state="visible", timeout=5000)
            chat_box.click()
            chat_box.fill(message)
            time.sleep(0.5)
            chat_box.press("Enter")
            
            # Περιμένουμε λίγο να φύγει το μήνυμα πριν κλείσουμε
            time.sleep(3)

            return f"✅ Επιτυχία: Το μήνυμα στάλθηκε στον/στην '{final_name}'."
            
    except Exception as e:
        return f"❌ Σφάλμα Messenger: {str(e)}"
    finally:
        try:
            browser.close()
        except:
            pass
@tool
def search_google_places(query: str, location: str = "Thessaloniki") -> str:
    """
    Αναζητά εστιατόρια, καφέ και μέρη για έξοδο μέσω Google Places API (New).
    Επιστρέφει όνομα, βαθμολογία, διεύθυνση, τύπο, τηλέφωνο, website, delivery και reviews.
    """
    import requests
    import os
    import urllib.parse
    import time
    import json
    from config import GPS_STORAGE_FILE
    
    # [MASTRO-GPS-INTERCEPTOR]
    if "κοντά" in query.lower() or location == "current":
        if os.path.exists(GPS_STORAGE_FILE):
            try:
                with open(GPS_STORAGE_FILE, "r") as f:
                    gps = json.load(f)
                    # Αν το στίγμα είναι φρέσκο (τελευταία 24ωρα)
                    if time.time() - gps['timestamp'] < 86400:
                        location = f"{gps['lat']},{gps['lon']}"
                        print(f"📍 [Web Tool]: Χρήση Live GPS στίγματος: {location}")
            except: pass
            
    api_key = os.getenv("GOOGLE_PLACES_API_KEY", "")
    print(f"DEBUG KEY: {api_key[:10]}...")
    if not api_key:
        return "❌ Λείπει το GOOGLE_PLACES_API_KEY από το .env"

    # ── 1. Text Search για να βρούμε places ──────────────────────
    search_text = f"{query} {location}"
    search_url = "https://places.googleapis.com/v1/places:searchText"

    # [MASTRO-UPGRADE]: Προσθέσαμε Phone, Website, Takeout, Delivery, DineIn και Reviews στο FieldMask
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": (
            "places.displayName,"
            "places.rating,"
            "places.userRatingCount,"
            "places.formattedAddress,"
            "places.primaryTypeDisplayName,"
            "places.regularOpeningHours,"
            "places.googleMapsUri,"
            "places.priceLevel,"
            "places.nationalPhoneNumber,"
            "places.websiteUri,"
            "places.takeout,"
            "places.delivery,"
            "places.dineIn,"
            "places.reviews"
        )
    }

    payload = {
        "textQuery": search_text,
        "languageCode": "el",
        "regionCode": "GR",
        "maxResultCount": 6
    }

    try:
        resp = requests.post(search_url, headers=headers, json=payload, timeout=10)
        
        if resp.status_code != 200:
            return f"❌ Google Places Error {resp.status_code}: {resp.text[:200]}"

        data = resp.json()
        places = data.get("places", [])

        if not places:
            return f"❌ Δεν βρέθηκαν αποτελέσματα για '{query}' στην {location}."

        # ── 2. Μορφοποίηση αποτελεσμάτων ─────────────────────────
        price_map = {
            "PRICE_LEVEL_FREE": "Δωρεάν",
            "PRICE_LEVEL_INEXPENSIVE": "€",
            "PRICE_LEVEL_MODERATE": "€€",
            "PRICE_LEVEL_EXPENSIVE": "€€€",
            "PRICE_LEVEL_VERY_EXPENSIVE": "€€€€"
        }

        lines = [f"📍 Αποτελέσματα για '{query}' — {location}:\n"]

        for i, place in enumerate(places, 1):
            name = place.get("displayName", {}).get("text", "Άγνωστο")
            rating = place.get("rating", "—")
            votes = place.get("userRatingCount", 0)
            address = place.get("formattedAddress", "Χωρίς διεύθυνση")
            ptype = place.get("primaryTypeDisplayName", {}).get("text", "")
            maps_url = place.get("googleMapsUri", "")
            price = price_map.get(place.get("priceLevel", ""), "")
            
            # Νέα Πεδία (Apify-style)
            phone = place.get("nationalPhoneNumber", "")
            website = place.get("websiteUri", "")
            
            # Επιλογές γεύματος (Delivery κλπ)
            services = []
            if place.get("takeout"): services.append("Takeout")
            if place.get("delivery"): services.append("Delivery")
            if place.get("dineIn"): services.append("Dine-in")
            
            # Κριτικές (παίρνουμε μόνο την πρώτη για να δούμε το "vibe")
# Κριτικές: Ανεβάσαμε το όριο στους 250 χαρακτήρες για να μη χάνεται το νόημα
            review_text = ""
            reviews = place.get("reviews", [])
            if reviews:
                first_rev = reviews[0].get("text", {}).get("text", "").replace("\n", " ").strip()
                if first_rev:
                    review_text = first_rev[:250] + "..." if len(first_rev) > 250 else first_rev

            # Ώρες λειτουργίας
            hours_info = ""
            opening = place.get("regularOpeningHours", {})
            if opening.get("openNow") is True:
                hours_info = " · ✅ Ανοιχτό"
            elif opening.get("openNow") is False:
                hours_info = " · 🔴 Κλειστό"

            # String Formatting 
            price_str = f" · {price}" if price else ""
            rating_str = f"⭐ {rating} ({votes} κριτικές)" if rating != "—" else "Χωρίς βαθμολογία"
            type_str = f" · {ptype}" if ptype else ""
            
            contact_str = ""
            if phone: contact_str += f"   📞 {phone}\n"
            # [MASTRO-FIX]: HTML Tags για να είναι σίγουρα κλικαριστά στο Telegram
            if website: contact_str += f"   🌐 <a href='{website}'>Website Μαγαζιού</a>\n"
            
            services_str = f"   🛵 [{', '.join(services)}]\n" if services else ""
            review_str = f"   💬 \"{review_text}\"\n" if review_text else ""

            # [MASTRO-FIX]: HTML Tag για το Google Maps
            lines.append(
                f"{i}. **{name}**{price_str}\n"
                f"   {rating_str}{type_str}{hours_info}\n"
                f"   📌 {address}\n"
                f"{contact_str}"
                f"{services_str}"
                f"{review_str}"
                f"   🗺️ <a href='{maps_url}'>Άνοιγμα στο Google Maps</a>\n"
            )

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Σφάλμα: {str(e)}"

@tool
def get_navigation_info(destination: str) -> str:
    """Παρέχει κλικαριστά links για χάρτη και πλοήγηση από Piston 7."""
    home_base = "Piston 7, Thessaloniki"
    dest_clean = f"{destination}, Thessaloniki".replace(" ", "+")
    home_clean = home_base.replace(" ", "+")

    search_url = f"https://www.google.com/maps/search/?api=1&query={dest_clean}"
    directions_url = f"https://www.google.com/maps/dir/?api=1&origin={home_clean}&destination={dest_clean}"

    return (
        f"📍 **Τοποθεσία:** {destination}\n\n"
        f"🔗 [Προβολή στον Χάρτη]({search_url})\n"
        f"🌐 Link: {search_url}\n\n"
        f"🚗 [Οδηγίες πλοήγησης από Piston 7]({directions_url})\n"
        f"🛣️ Διαδρομή: {directions_url}"
    )