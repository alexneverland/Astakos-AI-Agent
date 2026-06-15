import sqlite3
conn = sqlite3.connect('test.db')
with conn:
    pass
print('Result after with:', conn.execute('SELECT 1').fetchone())
conn.close()
