import sqlite3
import os

# Отримуємо корінь проєкту (на рівень вище папки core)
CORE_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(CORE_DIR)
DB_DIR = os.path.join(BASE_DIR, "data")
DB_FILE = os.path.join(DB_DIR, "settings.db")

def init_db():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    
    cursor.execute("""CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE, password_hash TEXT)""")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY, user_id INTEGER, ip_address TEXT, 
            user_agent TEXT, created_at REAL, expires_at REAL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    
    cursor.execute("""CREATE TABLE IF NOT EXISTS vendor (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, comment TEXT, deleted INTEGER DEFAULT 0)""")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS filament (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, vendor_id INTEGER, 
            material TEXT, price REAL, density REAL NOT NULL, diameter REAL NOT NULL, 
            weight REAL, spool_weight REAL, color_hex TEXT, comment TEXT, 
            settings_extruder_temp INTEGER, settings_bed_temp INTEGER, deleted INTEGER DEFAULT 0,
            FOREIGN KEY(vendor_id) REFERENCES vendor(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS spool (
            id INTEGER PRIMARY KEY AUTOINCREMENT, filament_id INTEGER, registered TEXT, 
            first_used TEXT, last_used TEXT, initial_weight REAL, spool_weight REAL, 
            used_weight REAL NOT NULL DEFAULT 0.0, comment TEXT, archived INTEGER DEFAULT 0, 
            price REAL, extra TEXT, FOREIGN KEY(filament_id) REFERENCES filament(id)
        )
    """)
    cursor.execute("""CREATE TABLE IF NOT EXISTS location (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, comment TEXT)""")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS printers (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, type TEXT NOT NULL, 
            host TEXT NOT NULL, port INTEGER NOT NULL, api_key TEXT
        )
    """)
    
    try:
        cursor.execute("ALTER TABLE sessions ADD COLUMN ip_address TEXT")
        cursor.execute("ALTER TABLE sessions ADD COLUMN user_agent TEXT")
        cursor.execute("ALTER TABLE sessions ADD COLUMN created_at REAL")
    except sqlite3.OperationalError:
        pass
        
    conn.commit()
    conn.close()
    print("[SQLITE LOG] Базу даних успішно ініціалізовано.", flush=True)

def save_ip_to_db(ip: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('printer_ip', ?)", (ip,))
    conn.commit()
    conn.close()