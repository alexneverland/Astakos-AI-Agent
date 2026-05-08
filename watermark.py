import os

# ΟΡΙΣΕ ΤΗΝ "ΣΦΡΑΓΙΔΑ" ΣΟΥ
HEADER = """# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: Lazaros (Piston-7)
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================
"""

# Ποια αρχεία να πειράξει
EXTENSIONS = ('.py', '.js', '.html', '.css')
# Ποιους φακέλους να αγνοήσει
IGNORE_DIRS = {'venv', '.git', '__pycache__', '.cache'}

def apply_watermark():
    count = 0
    for root, dirs, files in os.walk("."):
        # Φιλτράρισμα φακέλων
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        
        for file in files:
            if file.endswith(EXTENSIONS):
                file_path = os.path.join(root, file)
                
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Έλεγχος αν υπάρχει ήδη η σφραγίδα
                if "Project: Astakos AI Agent" not in content:
                    print(f"Adding watermark to: {file_path}")
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(HEADER + "\n" + content)
                    count += 1
                else:
                    print(f"Skipping (already marked): {file_path}")
    
    print(f"\n✅ Ολοκληρώθηκε! Η σφραγίδα μπήκε σε {count} αρχεία.")

if __name__ == "__main__":
    apply_watermark()