def calculate_bill_cost(consumption_kwh, previous_balance, current_fixed_charges, municipal_charges, vat_rate=0.06):
    """
    Υπολογίζει το κόστος του λογαριασμού ρεύματος με βάση τα στοιχεία του PDF.
    """
    # Τιμές από τον λογαριασμό
    tier1_limit = 101
    tier1_rate = 0.13630
    tier2_rate = 0.14500
    kot_discount = 0.07500
    etmear_rate = 0.01700
    
    # Χρέωση ενέργειας
    if consumption_kwh <= tier1_limit:
        energy_charge = consumption_kwh * tier1_rate
    else:
        energy_charge = (tier1_limit * tier1_rate) + ((consumption_kwh - tier1_limit) * tier2_rate)
    
    # Έκπτωση ΚΟΤ
    discount = consumption_kwh * kot_discount
    
    # Ρυθμιζόμενες χρεώσεις (ΕΤΜΕΑΡ)
    etmear_charge = consumption_kwh * etmear_rate
    
    # Σύνολο προ ΦΠΑ
    subtotal = energy_charge + current_fixed_charges + etmear_charge - discount
    
    # ΦΠΑ
    vat = subtotal * vat_rate
    
    # Τελικό ποσό τρέχοντος
    total_current = subtotal + vat + municipal_charges
    
    # Συνολικό ποσό με παλαιότερο χρέος
    total_to_pay = total_current + previous_balance
    
    return {
        "energy_charge": round(energy_charge, 2),
        "discount": round(discount, 2),
        "etmear": round(etmear_charge, 2),
        "subtotal_pre_vat": round(subtotal, 2),
        "vat": round(vat, 2),
        "total_current": round(total_current, 2),
        "total_to_pay": round(total_to_pay, 2)
    }

# Τεστ με τα δεδομένα του λογαριασμού
# 133 kWh, 110€ ανεξόφλητο, 4.83 πάγια, 13.09 δημοτικά
result = calculate_bill_cost(133, 110, 4.83, 13.09)
print(result)
