import os
print("Files in current directory:", os.listdir('.'))
if os.path.exists('astakos_skills'):
    print("Files in astakos_skills:", os.listdir('astakos_skills'))
else:
    print("Folder astakos_skills not found.")