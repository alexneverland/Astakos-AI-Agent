def calculate_bill_cost(consumption_kwh, previous_balance, current_fixed_charges, municipal_charges, vat_rate=0.06):
    """
    Calculates the electricity bill cost based on the PDF data.
    """
    # Values from the account
    tier1_limit = 101
    tier1_rate = 0.13630
    tier2_rate = 0.14500
    kot_discount = 0.07500
    etmear_rate = 0.01700
    
    # Energy charge
    if consumption_kwh <= tier1_limit:
        energy_charge = consumption_kwh * tier1_rate
    else:
        energy_charge = (tier1_limit * tier1_rate) + ((consumption_kwh - tier1_limit) * tier2_rate)
    
    # Social Residential Tariff (KOT) Discount
    discount = consumption_kwh * kot_discount
    
    # Regulated charges (ETMEAR)
    etmear_charge = consumption_kwh * etmear_rate
    
    # Total before VAT
    subtotal = energy_charge + current_fixed_charges + etmear_charge - discount
    
    # VAT
    vat = subtotal * vat_rate
    
    # Final amount of current
    total_current = subtotal + vat + municipal_charges
    
    # Total amount with older debt
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

# Test with the account data
# 133 kWh, 110€ unpaid balance, 4.83 standing charges, 13.09 municipal fees
result = calculate_bill_cost(133, 110, 4.83, 13.09)
print(result)
