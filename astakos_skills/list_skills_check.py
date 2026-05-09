import os

skills_path = r'C:\astakos_v2\astakos_skills'
if os.path.exists(skills_path):
    files = os.listdir(skills_path)
    print("Skills found:", files)
else:
    print("Skills directory not found.")
