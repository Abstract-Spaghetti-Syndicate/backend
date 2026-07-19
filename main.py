import sqlite3
import socket
import time
import os
import json
import hashlib
import asyncio
import httpx
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Header, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from zeroconf import Zeroconf, ServiceBrowser, ServiceListener
from printer_manager import PrinterManager

# --- Налаштування Бази даних ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(BASE_DIR, "data")
DB_FILE = os.path.join(DB_DIR, "settings.db")

def init_db():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    
    # Таблиця налаштувань
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    # Таблиця користувачів
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            password_hash TEXT
        )
    """)
    # Таблиця активних сесій
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER,
            ip_address TEXT,
            user_agent TEXT,
            created_at REAL,
            expires_at REAL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    
    # --- ТАБЛИЦІ ФІЛАМЕНТУ (Сумісні зі Spoolman) ---

    # Таблиця Виробників (vendor)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vendor (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            comment TEXT,
            deleted INTEGER DEFAULT 0
        )
    """)

    # Таблиця Типів філаменту (filament)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS filament (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            vendor_id INTEGER,
            material TEXT,
            price REAL,
            density REAL NOT NULL,
            diameter REAL NOT NULL,
            weight REAL,
            spool_weight REAL,
            color_hex TEXT,
            comment TEXT,
            settings_extruder_temp INTEGER,
            settings_bed_temp INTEGER,
            deleted INTEGER DEFAULT 0,
            FOREIGN KEY(vendor_id) REFERENCES vendor(id)
        )
    """)

    # Таблиця Котушок (spool)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS spool (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filament_id INTEGER,
            registered TEXT,
            first_used TEXT,
            last_used TEXT,
            initial_weight REAL,
            spool_weight REAL,
            used_weight REAL NOT NULL DEFAULT 0.0,
            comment TEXT,
            archived INTEGER DEFAULT 0,
            price REAL,
            extra TEXT,
            FOREIGN KEY(filament_id) REFERENCES filament(id)
        )
    """)

    # Нова таблиця принтерів
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS printers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            host TEXT NOT NULL,
            port INTEGER NOT NULL,
            api_key TEXT
        )
    """)
    
    try:
        cursor.execute("ALTER TABLE sessions ADD COLUMN ip_address TEXT")
        cursor.execute("ALTER TABLE sessions ADD COLUMN user_agent TEXT")
        cursor.execute("ALTER TABLE sessions ADD COLUMN created_at REAL")
    except sqlite3.OperationalError:
        pass  # Колонки вже існують
        
    conn.commit()
    conn.close()
    print("[SQLITE LOG] Базу даних успішно ініціалізовано.", flush=True)

# --- Парсер User-Agent ---
def parse_user_agent(ua_string: str) -> str:
    if not ua_string:
        return "Невідомий пристрій"
    
    ua_string = ua_string.lower()
    os_name = "Unknown OS"
    if "windows" in ua_string:
        os_name = "Windows"
    elif "android" in ua_string:
        os_name = "Android"
    elif "iphone" in ua_string or "ipad" in ua_string or "ipod" in ua_string:
        os_name = "iOS"
    elif "macintosh" in ua_string or "mac os" in ua_string:
        os_name = "macOS"
    elif "linux" in ua_string:
        os_name = "Linux"
    elif "x11" in ua_string:
        os_name = "Unix/Linux"
        
    browser_name = "Unknown Browser"
    if "vivaldi" in ua_string:
        browser_name = "Vivaldi"
    elif "yabrowser" in ua_string:
        browser_name = "Yandex Browser"
    elif "opr" in ua_string or "opera" in ua_string or "opios" in ua_string:
        browser_name = "Opera"
    elif "edg" in ua_string or "edge" in ua_string or "edgios" in ua_string or "edga" in ua_string:
        browser_name = "Edge"
    elif "brave" in ua_string:
        browser_name = "Brave"
    elif "electron" in ua_string:
        browser_name = "Electron App"
    elif "vscode" in ua_string or "code/" in ua_string:
        browser_name = "VS Code Browser"
    elif "firefox" in ua_string or "fxios" in ua_string:
        browser_name = "Firefox"
    elif "chrome" in ua_string or "chromium" in ua_string or "crios" in ua_string:
        browser_name = "Chrome"
    elif "safari" in ua_string:
        browser_name = "Safari"
        
    return f"{browser_name} ({os_name})"

# --- Безпечне хешування паролів ---
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    pwdhash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
    return salt.hex() + ":" + pwdhash.hex()

def verify_password(stored_password: str, provided_password: str) -> bool:
    try:
        salt_hex, hash_hex = stored_password.split(":")
        salt = bytes.fromhex(salt_hex)
        pwdhash = hashlib.pbkdf2_hmac("sha256", provided_password.encode("utf-8"), salt, 100000)
        return pwdhash.hex() == hash_hex
    except Exception:
        return False

# --- Керування сесіями ---
def create_session(user_id: int, ip_address: str, user_agent: str) -> str:
    token = os.urandom(24).hex()
    created_at = time.time()
    expires_at = created_at + (30 * 24 * 3600)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO sessions (token, user_id, ip_address, user_agent, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
        (token, user_id, ip_address, user_agent, created_at, expires_at)
    )
    conn.commit()
    conn.close()
    return token

def verify_session_token(token: str) -> int:
    if not token:
        raise HTTPException(status_code=401, detail="Токен відсутній")
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, expires_at FROM sessions WHERE token=?", (token,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=401, detail="Невірний або застарілий токен")
    
    user_id, expires_at = row
    if time.time() > expires_at:
        raise HTTPException(status_code=401, detail="Термін дії сесії закінчився")
    return user_id

# Ініціалізація схеми безпеки
security_scheme = HTTPBearer()

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security_scheme)):
    return verify_session_token(credentials.credentials)

# --- Робота з IP ---
def get_saved_ip() -> str:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key='printer_ip'")
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else ""

def save_ip_to_db(ip: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('printer_ip', ?)", (ip,))
    conn.commit()
    conn.close()

# --- mDNS сканер ---
class MoonrakerListener(ServiceListener):
    def __init__(self):
        self.printers = []
    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        info = zc.get_service_info(type_, name)
        if info:
            addresses = [socket.inet_ntoa(addr) for addr in info.addresses]
            self.printers.append({
                "name": name.split('.')[0],
                "ip": addresses[0] if addresses else "unknown",
                "port": info.port
            })
    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None: pass
    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None: pass

def scan_network_for_printers() -> list:
    zc = Zeroconf()
    listener = MoonrakerListener()
    browser = ServiceBrowser(zc, "_moonraker._tcp.local.", listener)
    time.sleep(2.0)
    zc.close()
    return listener.printers


# --- Ініціалізація додатку ---
init_db()
manager = PrinterManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # При старті сервера завантажуємо та запускаємо всі принтери у фонових процесах
    manager.load_all_printers()
    yield
    # При зупинці вимикаємо всі фонові процеси
    await manager.shutdown()

app = FastAPI(title="Secure Klipper Hub", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Моделі даних API ---
class RegisterRequest(BaseModel):
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class IPRequest(BaseModel):
    ip: str
    type: str = "klipper"      # "klipper" чи "octoprint"
    api_key: str = ""          # Ключ авторизації для OctoPrint

class RevokeRequest(BaseModel):
    token: str

class SpoolmanImportRequest(BaseModel):
    spoolman_url: str

class NewPrinterRequest(BaseModel):
    name: str
    type: str  # "klipper" чи "octoprint"
    host: str
    port: int
    api_key: str = None


# --- АВТОРИЗАЦІЙНІ ЕНДПОІНТИ ---

@app.get("/api/auth/status")
def get_auth_status():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    count = cursor.fetchone()[0]
    conn.close()
    return {"is_registered": count > 0}

@app.post("/api/auth/register")
def register_user(payload: RegisterRequest, request: Request):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    count = cursor.fetchone()[0]
    
    if count > 0:
        conn.close()
        raise HTTPException(status_code=400, detail="Реєстрація закрита. Адміністратора вже створено.")
    
    hashed = hash_password(payload.password)
    try:
        cursor.execute("INSERT INTO users (email, password_hash) VALUES (?, ?)", (payload.email, hashed))
        conn.commit()
        user_id = cursor.lastrowid
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=f"Помилка створення: {e}")
    conn.close()
    
    ip = request.client.host if request.client else "unknown"
    ua = request.headers.get("user-agent", "unknown")
    token = create_session(user_id, ip, ua)
    return {"status": "success", "token": token}

@app.post("/api/auth/login")
def login_user(payload: LoginRequest, request: Request):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, password_hash FROM users WHERE email=?", (payload.email,))
    row = cursor.fetchone()
    conn.close()
    
    if not row or not verify_password(row[1], payload.password):
        raise HTTPException(status_code=401, detail="Невірний email або пароль")
    
    ip = request.client.host if request.client else "unknown"
    ua = request.headers.get("user-agent", "unknown")
    token = create_session(row[0], ip, ua)
    return {"status": "success", "token": token}


# --- УПРАВЛІННЯ ПРИСТРОЯМИ (СЕСІЯМИ) ---

@app.get("/api/auth/sessions")
def get_active_sessions(credentials: HTTPAuthorizationCredentials = Depends(security_scheme)):
    """Отримати список усіх підключених пристроїв"""
    current_token = credentials.credentials
    current_user_id = verify_session_token(current_token)
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT token, ip_address, user_agent, created_at FROM sessions WHERE user_id=?", (current_user_id,))
    rows = cursor.fetchall()
    conn.close()
    
    sessions_list = []
    for row in rows:
        token, ip, ua, created_at = row
        readable_device = parse_user_agent(ua)
        readable_date = datetime.fromtimestamp(created_at).strftime("%d.%m.%Y %H:%M") if created_at else "Невідомо"
        
        sessions_list.append({
            "token": token,
            "device": readable_device,
            "ip": ip or "unknown",
            "date": readable_date,
            "is_current": token == current_token
        })
    return sessions_list

@app.post("/api/auth/sessions/revoke")
def revoke_session(payload: RevokeRequest, credentials: HTTPAuthorizationCredentials = Depends(security_scheme)):
    current_token = credentials.credentials
    verify_session_token(current_token)
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sessions WHERE token=?", (payload.token,))
    conn.commit()
    conn.close()
    return {"status": "success"}


# --- ЗАХИЩЕНІ ЕНДПОІНТИ ПРИНТЕРІВ (Мультипринтерні) ---

@app.get("/api/printers", dependencies=[Depends(get_current_user)])
def get_printers_list():
    """Повертає список усіх зареєстрованих принтерів з SQLite для малювання вкладок"""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, type, host, port FROM printers ORDER BY id ASC")
        rows = cursor.fetchall()
        conn.close()
        
        printers = []
        for r in rows:
            printers.append({
                "id": r[0],
                "name": r[1],
                "type": r[2],
                "host": r[3],
                "port": r[4]
            })
        return {"status": "success", "printers": printers}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Помилка зчитування списку принтерів: {str(e)}")

@app.post("/api/printers", dependencies=[Depends(get_current_user)])
async def add_new_printer(payload: NewPrinterRequest):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO printers (name, type, host, port, api_key) VALUES (?, ?, ?, ?, ?)",
        (payload.name, payload.type, payload.host, payload.port, payload.api_key)
    )
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    
    # Відразу «на льоту» ініціалізуємо та запускаємо новий принтер у фоні!
    manager.start_printer_client(new_id, payload.type, payload.host, payload.port, payload.api_key)
    return {"status": "success", "printer_id": new_id}

@app.get("/api/printers/{printer_id}/status", dependencies=[Depends(get_current_user)])
async def get_printer_status(printer_id: int):
    client = manager.clients.get(printer_id)
    if not client:
        raise HTTPException(status_code=404, detail="Принтер не знайдено або він не запущений")
    return {
        "printer_id": printer_id,
        "connected": client.is_connected,
        "telemetry": client.state
    }


# --- ШАР СУМІСНОСТІ З ОДНОПРИНТЕРНИМ ТЕСТОВИМ UI ---

@app.get("/printer/status", dependencies=[Depends(get_current_user)])
async def get_status_compatibility():
    if not manager.clients:
        return {
            "configured_ip": "Не налаштовано",
            "connected": False,
            "telemetry": {
                "temps": {
                    "extruder": {"current": 0.0, "target": 0.0},
                    "bed": {"current": 0.0, "target": 0.0},
                    "chamber": {"current": 0.0, "target": 0.0}
                },
                "fans": {"part_cooling": 0.0},
                "print_state": "not_configured",
                "raw_telemetry": {}
            }
        }
    
    first_id = list(manager.clients.keys())[0]
    client = manager.clients[first_id]
    
    return {
        "configured_ip": client.host,
        "connected": client.is_connected,
        "telemetry": client.state
    }

@app.post("/settings/printer-ip", dependencies=[Depends(get_current_user)])
async def update_printer_ip_compatibility(payload: IPRequest):
    ip = payload.ip.strip()
    p_type = payload.type.strip().lower()
    api_key = payload.api_key.strip() if payload.api_key else ""
    
    if not ip:
        raise HTTPException(status_code=400, detail="IP не може бути пустим")
    save_ip_to_db(ip)
    
    # Визначаємо порт та хост
    host = ip
    port = 7125 if p_type == "klipper" else 5000
    if ":" in ip:
        try:
            host, port_str = ip.split(":")
            port = int(port_str)
        except Exception:
            pass

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM printers WHERE name='Default Printer'")
    row = cursor.fetchone()
    
    if row:
        p_id = row[0]
        cursor.execute(
            "UPDATE printers SET type=?, host=?, port=?, api_key=? WHERE id=?",
            (p_type, host, port, api_key, p_id)
        )
        conn.commit()
        conn.close()
        
        # Миттєво перезапускаємо клієнт
        if p_id in manager.clients:
            await manager.stop_printer_client(p_id)
        manager.start_printer_client(p_id, p_type, host, port, api_key)
    else:
        cursor.execute(
            "INSERT INTO printers (name, type, host, port, api_key) VALUES ('Default Printer', ?, ?, ?, ?)",
            (p_type, host, port, api_key)
        )
        conn.commit()
        new_id = cursor.lastrowid
        conn.close()
        manager.start_printer_client(new_id, p_type, host, port, api_key)
        
    return {"status": "success", "saved_ip": ip, "type": p_type}


# --- ЕНДПОІНТИ КЕРУВАННЯ ФІЛАМЕНТОМ (SPOOLMAN) ---

@app.get("/api/spools", dependencies=[Depends(get_current_user)])
def get_spools_list():
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                spool.id, 
                vendor.name, 
                filament.name, 
                filament.material, 
                COALESCE(spool.initial_weight, filament.weight, 1000.0) AS initial, 
                spool.used_weight,
                filament.color_hex
            FROM spool
            JOIN filament ON spool.filament_id = filament.id
            JOIN vendor ON filament.vendor_id = vendor.id
            WHERE spool.archived = 0
            ORDER BY spool.id DESC
        """)
        rows = cursor.fetchall()
        conn.close()
        
        spools = []
        for r in rows:
            spools.append({
                "id": r[0],
                "vendor": r[1],
                "name": r[2],
                "material": r[3],
                "initial_weight": r[4],
                "used_weight": r[5],
                "color_hex": r[6]
            })
        return {"status": "success", "spools": spools}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Помилка зчитування бази: {str(e)}")

@app.post("/api/spoolman/import", dependencies=[Depends(get_current_user)])
async def import_from_spoolman(payload: SpoolmanImportRequest):
    base_url = payload.spoolman_url.strip().rstrip("/")
    if not base_url.endswith("/api/v1"):
        base_url = f"{base_url}/api/v1"
        
    print(f"[SPOOLMAN IMPORT] Початок імпорту з {base_url}...", flush=True)
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            v_resp = await client.get(f"{base_url}/vendor")
            if v_resp.status_code != 200:
                raise HTTPException(status_code=400, detail=f"Помилка завантаження виробників: {v_resp.status_code}")
            vendors = v_resp.json()
            
            f_resp = await client.get(f"{base_url}/filament")
            if f_resp.status_code != 200:
                raise HTTPException(status_code=400, detail=f"Помилка завантаження пластику: {f_resp.status_code}")
            filaments = f_resp.json()
            
            s_resp = await client.get(f"{base_url}/spool")
            if s_resp.status_code != 200:
                raise HTTPException(status_code=400, detail=f"Помилка завантаження котушок: {s_resp.status_code}")
            spools = s_resp.json()

        print("[SPOOLMAN IMPORT] Дані завантажено. Запис в SQLite...", flush=True)

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys = OFF")

        for v in vendors:
            cursor.execute("""
                INSERT OR REPLACE INTO vendor (id, name, comment, deleted)
                VALUES (?, ?, ?, ?)
            """, (v.get("id"), v.get("name"), v.get("comment"), 1 if v.get("deleted") else 0))
            
        for f in filaments:
            vendor_id = f.get("vendor", {}).get("id") if f.get("vendor") else None
            cursor.execute("""
                INSERT OR REPLACE INTO filament (
                    id, name, vendor_id, material, price, density, diameter, 
                    weight, spool_weight, color_hex, comment, 
                    settings_extruder_temp, settings_bed_temp, deleted
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                f.get("id"), f.get("name"), vendor_id, f.get("material"),
                f.get("price"), f.get("density"), f.get("diameter"),
                f.get("weight"), f.get("spool_weight"), f.get("color_hex"),
                f.get("comment"), f.get("settings_extruder_temp"),
                f.get("settings_bed_temp"), 1 if f.get("deleted") else 0
            ))

        for s in spools:
            filament_id = s.get("filament", {}).get("id") if s.get("filament") else None
            extra_val = json.dumps(s.get("extra")) if s.get("extra") else None
            
            cursor.execute("""
                INSERT OR REPLACE INTO spool (
                    id, filament_id, registered, first_used, last_used, 
                    initial_weight, spool_weight, used_weight, comment, archived, price, extra
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                s.get("id"), filament_id, s.get("registered"), s.get("first_used"),
                s.get("last_used"), s.get("initial_weight"), s.get("spool_weight"),
                s.get("used_weight", 0.0), s.get("comment"), 1 if s.get("archived") else 0,
                s.get("price"), extra_val
            ))

        cursor.execute("PRAGMA foreign_keys = ON")
        conn.commit()
        conn.close()
        
        print(f"[SPOOLMAN IMPORT SUCCESS] Успішно імпортовано: {len(vendors)} виробників, {len(filaments)} пластику, {len(spools)} котушок.", flush=True)
        return {
            "status": "success",
            "imported": {
                "vendors": len(vendors),
                "filaments": len(filaments),
                "spools": len(spools)
            }
        }
    except Exception as e:
        print(f"[SPOOLMAN IMPORT ERROR] Помилка: {e}", flush=True)
        raise HTTPException(status_code=500, detail=f"Помилка імпорту: {str(e)}")


# --- Візуальний інтерфейс (HTML + JS) ---
@app.get("/", response_class=HTMLResponse)
def get_home_page():
    # Зчитуємо HTML-шаблон з окремого файлу
    html_path = os.path.join(BASE_DIR, "templates", "index.html")
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Файл шаблону templates/index.html не знайдено.")