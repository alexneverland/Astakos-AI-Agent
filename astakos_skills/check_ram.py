import subprocess

# Χρήση καθαρής PowerShell εντολής χωρίς εξωτερικές βιβλιοθήκες Python
command = "powershell -Command \"(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1024\""
try:
    result = subprocess.check_output(command, shell=True, text=True)
    free_ram_mb = float(result.strip())
    print(f"Ελεύθερη RAM: {free_ram_mb:.2f} MB")
except Exception as e:
    print(f"Σφάλμα: {e}")