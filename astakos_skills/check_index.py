import os

# Ψάχνω στο τρέχον path (astakos_skills) και ένα επίπεδο πάνω
files = os.listdir('.')
files_parent = os.listdir('..')

print(f"Files in current folder: {files}")
print(f"Files in parent folder: {files_parent}")

# Έλεγχος αν υπάρχει index αρχείο
found = False
for f in files + files_parent:
    if 'index' in f.lower():
        print(f"Βρέθηκε αρχείο: {f}")
        found = True

if not found:
    print("Δεν βρέθηκε αρχείο index.")
