with open('tools/system.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()
    for i, line in enumerate(lines):
        if 'def mail_manager' in line:
            print("".join(lines[i:i+100]))
            break