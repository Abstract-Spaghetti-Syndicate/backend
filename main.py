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
from pydantic import BaseModel
from zeroconf import Zeroconf, ServiceBrowser, ServiceListener
from klipper_client import KlipperClient

# --- Налаштування Бази даних ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(BASE_DIR, "data")
DB_FILE = os.path.join(DB_DIR, "settings.db")

def init_db():
    # Створюємо абсолютний шлях до папки data, якщо її немає
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
    if token.startswith("Bearer "):
        token = token[7:]

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

async def get_current_user(authorization: str = Header(None)):
    return verify_session_token(authorization)

# --- Робота з IP принтера ---
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
saved_ip = get_saved_ip()
klipper = KlipperClient(host=saved_ip)

@asynccontextmanager
async def lifespan(app: FastAPI):
    listener_task = asyncio.create_task(klipper.start_websocket_listener())
    yield
    listener_task.cancel()

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

class RevokeRequest(BaseModel):
    token: str

class SpoolmanImportRequest(BaseModel):
    spoolman_url: str


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
def get_active_sessions(authorization: str = Header(None)):
    current_token = authorization
    if current_token and current_token.startswith("Bearer "):
        current_token = current_token[7:]
        
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
def revoke_session(payload: RevokeRequest, authorization: str = Header(None)):
    current_token = authorization
    if current_token and current_token.startswith("Bearer "):
        current_token = current_token[7:]
    verify_session_token(current_token)
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sessions WHERE token=?", (payload.token,))
    conn.commit()
    conn.close()
    return {"status": "success"}


# --- ЗАХИЩЕНІ ЕНДПОІНТИ ПРИНТЕРА ---

@app.get("/printer/status", dependencies=[Depends(get_current_user)])
async def get_status():
    return {
        "configured_ip": klipper.host,
        "connected": klipper.is_connected,
        "telemetry": klipper.state
    }

@app.post("/settings/printer-ip", dependencies=[Depends(get_current_user)])
async def update_printer_ip(payload: IPRequest):
    ip = payload.ip.strip()
    if not ip:
        raise HTTPException(status_code=400, detail="IP не може бути пустим")
    save_ip_to_db(ip)
    await klipper.update_host_and_reconnect(ip)
    return {"status": "success", "saved_ip": ip}

@app.post("/settings/scan", dependencies=[Depends(get_current_user)])
def scan_printers():
    return {"status": "success", "printers": scan_network_for_printers()}


# --- ЕНДПОІНТИ КЕРУВАННЯ ФІЛАМЕНТОМ (SPOOLMAN) ---

@app.get("/api/spools", dependencies=[Depends(get_current_user)])
def get_spools_list():
    """Повертає список неархівованих котушок у нашому єдиному стандарті"""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        # Об'єднуємо таблиці, вираховуємо вагу та підстраховуємося COALESCE, якщо initial_weight = NULL
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


# --- Веб-інтерфейс ---
@app.get("/", response_class=HTMLResponse)
def get_home_page():
    return """
    <!DOCTYPE html>
    <html lang="uk">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Unified Printer Hub (Secure Sessions)</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-gray-900 text-gray-100 font-sans min-h-screen flex items-center justify-center">
        
        <!-- Блок Авторизації -->
        <div id="auth-box" class="bg-gray-800 p-8 rounded-lg shadow-lg border border-gray-700 w-full max-w-md">
            <h2 id="auth-title" class="text-2xl font-bold text-center text-blue-500 mb-2">Завантаження...</h2>
            <p id="auth-subtitle" class="text-xs text-gray-400 text-center mb-6">Перевірка стану системи...</p>
            
            <form id="auth-form" onsubmit="handleAuth(event)" class="space-y-4">
                <div>
                    <label class="block text-xs text-gray-400 mb-1">Email</label>
                    <input id="auth-email" type="email" required class="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-500 text-white">
                </div>
                <div>
                    <label class="block text-xs text-gray-400 mb-1">Пароль</label>
                    <input id="auth-password" type="password" required class="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-500 text-white">
                </div>
                <button id="auth-btn" type="submit" class="w-full bg-blue-600 hover:bg-blue-500 text-white text-sm font-bold py-2.5 rounded transition">Увійти</button>
            </form>
        </div>

        <!-- Головна Панель Керування -->
        <div id="main-panel" class="container mx-auto p-6 max-w-4xl hidden self-start">
            <header class="mb-8 flex justify-between items-center">
                <div>
                    <h1 class="text-3xl font-extrabold text-blue-500">Abstract Spaghetti Syndicate</h1>
                    <p class="text-gray-400 text-xs">Безпечна панель моніторингу принтера</p>
                </div>
                <div>
                    <button onclick="handleLogout()" class="bg-gray-700 hover:bg-gray-600 text-white text-xs font-bold px-4 py-2 rounded transition">Вийти</button>
                </div>
            </header>

            <!-- Основна Сітка -->
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                <!-- Монітор -->
                <div class="bg-gray-800 p-6 rounded-lg shadow-lg border border-gray-700 flex flex-col h-[550px]">
                    <h2 class="text-xl font-bold mb-4 border-b border-gray-700 pb-2">Монітор принтера</h2>
                    <div class="space-y-2 mb-3">
                        <div class="flex justify-between items-center text-xs">
                            <span class="text-gray-400">IP принтера:</span>
                            <span id="current-ip" class="font-mono text-blue-400 font-bold">...</span>
                        </div>
                        <div class="flex justify-between items-center text-xs">
                            <span class="text-gray-400">Статус:</span>
                            <span id="connection-status" class="inline-block px-2 py-0.5 rounded text-[10px] font-bold bg-gray-700 text-gray-300">...</span>
                        </div>
                    </div>

                    <div class="grid grid-cols-2 gap-3 mb-4">
                        <div class="bg-gray-900 p-3 rounded text-center border border-gray-800">
                            <p class="text-[10px] text-gray-500 font-bold uppercase">Екструдер</p>
                            <p id="temp-extruder" class="text-xl font-extrabold text-red-500">0.0°C</p>
                            <p id="target-extruder" class="text-[10px] text-gray-400">Ціль: 0°C</p>
                        </div>
                        <div class="bg-gray-900 p-3 rounded text-center border border-gray-800">
                            <p class="text-[10px] text-gray-500 font-bold uppercase">Стіл</p>
                            <p id="temp-bed" class="text-xl font-extrabold text-yellow-500">0.0°C</p>
                            <p id="target-bed" class="text-[10px] text-gray-400">Ціль: 0°C</p>
                        </div>
                    </div>

                    <p class="text-[11px] font-bold text-gray-400 mb-1.5 uppercase tracking-wider">Усі датчики системи:</p>
                    <div id="dynamic-sensors-container" class="flex-1 overflow-y-auto space-y-2 pr-1 scrollbar-thin scrollbar-thumb-gray-700"></div>
                </div>

                <!-- Налаштування та пристрої -->
                <div class="space-y-6">
                    <!-- Налаштування IP -->
                    <div class="bg-gray-800 p-6 rounded-lg shadow-lg border border-gray-700">
                        <h2 class="text-lg font-bold text-white mb-2">Спосіб 1: Зберегти IP у базу (SQLite)</h2>
                        <div class="flex gap-2">
                            <input id="manual-ip-input" type="text" placeholder="напр. 192.168.1.115 або localhost" class="bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm flex-1 focus:outline-none focus:border-blue-500 text-mono text-white">
                            <button onclick="saveManualIP()" class="bg-blue-600 hover:bg-blue-500 text-white text-sm font-bold px-4 py-2 rounded transition">Зберегти</button>
                        </div>
                    </div>

                    <!-- Пошук mDNS -->
                    <div class="bg-gray-800 p-6 rounded-lg shadow-lg border border-gray-700">
                        <h2 class="text-lg font-bold text-white mb-2">Спосіб 2: Автоматичний пошук (mDNS)</h2>
                        <button id="scan-btn" onclick="startScan()" class="w-full bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-bold py-2 px-4 rounded transition">🔍 Сканувати мережу</button>
                        <div id="scan-results" class="mt-4 space-y-2 hidden">
                            <p class="text-xs font-semibold text-gray-400 border-b border-gray-700 pb-1">Знайдені пристрої:</p>
                            <div id="printers-list" class="max-h-40 overflow-y-auto space-y-2"></div>
                        </div>
                    </div>

                    <!-- Імпорт зі Spoolman -->
                    <div class="bg-gray-800 p-6 rounded-lg shadow-lg border border-gray-700">
                        <h2 class="text-lg font-bold text-white mb-2">Імпорт бази зі Spoolman</h2>
                        <p class="text-xs text-gray-400 mb-4">Синхронізувати всіх виробників, філаменти та котушки з віддаленого сервера.</p>
                        <div class="flex gap-2">
                            <input id="spoolman-url-input" type="text" placeholder="напр. http://192.168.1.50:7912" class="bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm flex-1 focus:outline-none focus:border-blue-500 text-mono text-white">
                            <button onclick="importFromSpoolman(this)" class="bg-purple-600 hover:bg-purple-500 text-white text-sm font-bold px-4 py-2 rounded transition">Імпортувати</button>
                        </div>
                    </div>

                    <!-- Список активних сесій -->
                    <div class="bg-gray-800 p-6 rounded-lg shadow-lg border border-gray-700">
                        <h2 class="text-lg font-bold text-white mb-1">Підключені пристрої</h2>
                        <p class="text-xs text-gray-400 mb-4">Список ваших активних сесій на інших гаджетах.</p>
                        <div id="sessions-list" class="space-y-2 max-h-44 overflow-y-auto pr-1"></div>
                    </div>
                </div>
            </div>

            <!-- Новий великий блок: Список котушок (на всю ширину знизу) -->
            <div class="bg-gray-800 p-6 rounded-lg shadow-lg border border-gray-700 mt-6">
                <h2 class="text-xl font-bold mb-2 border-b border-gray-700 pb-2">Мої котушки філаменту</h2>
                <p class="text-xs text-gray-400 mb-4">Список активних та імпортованих котушок, збережених у локальній базі даних.</p>
                
                <div id="spools-list-container" class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4 max-h-96 overflow-y-auto pr-1">
                    <p class="text-xs text-gray-500 py-6 text-center col-span-full">Очікування завантаження списку котушок...</p>
                </div>
            </div>

        </div>

        <script>
            let isSystemRegistered = false;
            let pollingInterval = null;

            async function checkAuthStatus() {
                try {
                    const response = await fetch("/api/auth/status");
                    const data = await response.json();
                    isSystemRegistered = data.is_registered;

                    const titleEl = document.getElementById("auth-title");
                    const subtitleEl = document.getElementById("auth-subtitle");
                    const btnEl = document.getElementById("auth-btn");

                    if (isSystemRegistered) {
                        titleEl.innerText = "Авторизація";
                        subtitleEl.innerText = "Увійдіть, щоб отримати доступ до принтера";
                        btnEl.innerText = "Увійти";
                    } else {
                        titleEl.innerText = "Первинне налаштування";
                        subtitleEl.innerText = "Створіть акаунт адміністратора системи";
                        btnEl.innerText = "Зареєструватися";
                    }

                    const token = localStorage.getItem("session_token");
                    if (token) {
                        showMainPanel();
                    }
                } catch (e) {
                    console.error("Помилка ініціалізації авторизації:", e);
                }
            }

            async function handleAuth(event) {
                event.preventDefault();
                const email = document.getElementById("auth-email").value;
                const password = document.getElementById("auth-password").value;

                const endpoint = isSystemRegistered ? "/api/auth/login" : "/api/auth/register";

                try {
                    const response = await fetch(endpoint, {
                        method: "POST",
                        headers: {"Content-Type": "application/json"},
                        body: JSON.stringify({email, password})
                    });

                    if (!response.ok) {
                        const err = await response.json();
                        alert("Помилка: " + (err.detail || "Невідома помилка"));
                        return;
                    }

                    const data = await response.json();
                    if (data.status === "success" && data.token) {
                        localStorage.setItem("session_token", data.token);
                        showMainPanel();
                    }
                } catch (e) {
                    alert("Помилка з'єднання з сервером.");
                }
            }

            function showMainPanel() {
                document.body.className = "bg-gray-900 text-gray-100 font-sans min-h-screen flex items-start justify-start";
                document.getElementById("auth-box").classList.add("hidden");
                document.getElementById("main-panel").classList.remove("hidden");
                
                if (!pollingInterval) {
                    pollingInterval = setInterval(pollStatus, 1500);
                    pollStatus();
                    loadSessions();
                    loadSpools(); // Завантажуємо котушки при вході
                }
            }

            function handleLogout() {
                localStorage.removeItem("session_token");
                if (pollingInterval) {
                    clearInterval(pollingInterval);
                    pollingInterval = null;
                }
                document.body.className = "bg-gray-900 text-gray-100 font-sans min-h-screen flex items-center justify-center";
                document.getElementById("main-panel").classList.add("hidden");
                document.getElementById("auth-box").classList.remove("hidden");
                checkAuthStatus();
            }

            async function secureFetch(url, options = {}) {
                const token = localStorage.getItem("session_token");
                if (!options.headers) options.headers = {};
                options.headers["Authorization"] = "Bearer " + token;

                const response = await fetch(url, options);
                if (response.status === 401) {
                    handleLogout();
                    throw new Error("Unauthorized");
                }
                return response;
            }

            async function loadSessions() {
                try {
                    const response = await secureFetch("/api/auth/sessions");
                    const data = await response.json();
                    const listDiv = document.getElementById("sessions-list");
                    listDiv.innerHTML = "";
                    
                    data.forEach(sess => {
                        const item = document.createElement("div");
                        item.className = "flex items-center justify-between bg-gray-900 p-2.5 rounded text-xs border border-gray-950";
                        const currentBadge = sess.is_current ? `<span class="bg-blue-900/60 text-blue-300 px-1 py-0.5 rounded text-[9px] font-bold">Цей пристрій</span>` : "";
                        
                        item.innerHTML = `
                            <div>
                                <span class="font-bold text-gray-200 block">${sess.device} ${currentBadge}</span>
                                <span class="text-gray-500 font-mono text-[10px]">${sess.ip} | ${sess.date}</span>
                            </div>
                            ${sess.is_current ? "" : `<button onclick="revokeSession('${sess.token}')" class="bg-rose-950/60 hover:bg-rose-900/80 text-rose-300 px-2 py-1 rounded transition text-[10px] font-bold">Закрити</button>`}
                        `;
                        listDiv.appendChild(item);
                    });
                } catch (e) {
                    console.error("Помилка завантаження сесій:", e);
                }
            }

            async function revokeSession(tokenToRevoke) {
                if (!confirm("Ви дійсно хочете закрити сесію для цього пристрою?")) return;
                try {
                    const response = await secureFetch("/api/auth/sessions/revoke", {
                        method: "POST",
                        headers: {"Content-Type": "application/json"},
                        body: JSON.stringify({token: tokenToRevoke})
                    });
                    const result = await response.json();
                    if (result.status === "success") {
                        loadSessions();
                    }
                } catch (e) {
                    alert("Помилка закриття сесії.");
                }
            }

            // Завантаження котушок на головний екран
            async function loadSpools() {
                try {
                    const response = await secureFetch("/api/spools");
                    const data = await response.json();
                    const container = document.getElementById("spools-list-container");
                    container.innerHTML = "";

                    if (data.status === "success" && data.spools.length > 0) {
                        data.spools.forEach(spool => {
                            const remaining = spool.initial_weight - spool.used_weight;
                            // Рахуємо відсоток залишку для красивого прогрес-бару
                            const percentage = Math.max(0, Math.min(100, (remaining / spool.initial_weight) * 100));
                            
                            const card = document.createElement("div");
                            card.className = "bg-gray-900 p-3.5 rounded border border-gray-800 flex flex-col justify-between";
                            
                            // Якщо у філамента в базі є колір HEX — малюємо кольоровий кружечок
                            const colorMarker = spool.color_hex ? `<span class="inline-block w-3 h-3 rounded-full border border-gray-700 mr-1.5 align-middle" style="background-color: #${spool.color_hex}"></span>` : "";

                            card.innerHTML = `
                                <div>
                                    <div class="flex justify-between items-start mb-1">
                                        <span class="text-gray-500 font-mono text-[10px] font-bold uppercase tracking-wider">${spool.vendor}</span>
                                        <span class="bg-blue-950/60 text-blue-300 text-[9px] font-bold px-1.5 py-0.5 rounded-full uppercase">${spool.material}</span>
                                    </div>
                                    <h3 class="text-xs font-bold text-gray-200 flex items-center mb-3">
                                        ${colorMarker}
                                        ${spool.name || "Філамент #" + spool.id}
                                    </h3>
                                </div>
                                <div class="space-y-1">
                                    <div class="flex justify-between text-[11px]">
                                        <span class="text-gray-400">Залишилося:</span>
                                        <span class="font-mono font-bold text-emerald-400">${remaining.toFixed(0)}г / ${spool.initial_weight.toFixed(0)}г</span>
                                    </div>
                                    <div class="w-full bg-gray-800 rounded-full h-1.5 overflow-hidden">
                                        <div class="bg-emerald-500 h-1.5 rounded-full transition-all duration-500" style="width: ${percentage}%"></div>
                                    </div>
                                </div>
                            `;
                            container.appendChild(card);
                        });
                    } else {
                        container.innerHTML = '<p class="text-xs text-gray-500 py-6 text-center col-span-full">У вашій базі немає жодної активної котушки. Виконайте імпорт або додайте котушки.</p>';
                    }
                } catch (e) {
                    console.error("Помилка завантаження котушок:", e);
                }
            }

            async function importFromSpoolman(btn) {
                const url = document.getElementById("spoolman-url-input").value;
                if (!url) return alert("Будь ласка, введіть URL вашого сервера Spoolman.");

                if (!confirm("Ви дійсно хочете завантажити дані? Це може перезаписати локальні записи з такими ж ID.")) return;

                const oldText = btn.innerText;
                btn.innerText = "⏳ Йде імпорт...";
                btn.disabled = true;

                try {
                    const response = await secureFetch("/api/spoolman/import", {
                        method: "POST",
                        headers: {"Content-Type": "application/json"},
                        body: JSON.stringify({spoolman_url: url})
                    });
                    
                    if (!response.ok) {
                        const err = await response.json();
                        alert("Помилка: " + (err.detail || "Не вдалося виконати імпорт"));
                        return;
                    }

                    const result = await response.json();
                    if (result.status === "success") {
                        alert("Успішно імпортовано:\\n- Виробників: " + result.imported.vendors + "\\n- Пластику: " + result.imported.filaments + "\\n- Котушок: " + result.imported.spools);
                        document.getElementById("spoolman-url-input").value = "";
                        
                        // АВТОМАТИЧНО оновлюємо список котушок на екрані відразу після імпорту!
                        loadSpools();
                    } else {
                        alert("Помилка імпорту.");
                    }
                } catch (e) {
                    alert("Помилка зв'язку з сервером під час імпорту.");
                } finally {
                    btn.innerText = oldText;
                    btn.disabled = false;
                }
            }

            async function pollStatus() {
                try {
                    const response = await secureFetch("/printer/status");
                    const data = await response.json();
                    
                    document.getElementById("current-ip").innerText = data.configured_ip || "Не налаштовано";
                    
                    const statusEl = document.getElementById("connection-status");
                    if (data.connected) {
                        statusEl.innerText = "ПІДКЛЮЧЕНО (" + data.telemetry.print_state.toUpperCase() + ")";
                        statusEl.className = "px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-900 text-emerald-300";
                    } else {
                        statusEl.innerText = "НЕМАЄ ЗВ'ЯЗКУ (" + data.telemetry.print_state.toUpperCase() + ")";
                        statusEl.className = "px-2 py-0.5 rounded text-[10px] font-bold bg-rose-950 text-rose-300";
                    }

                    document.getElementById("temp-extruder").innerText = data.telemetry.temps.extruder.current.toFixed(1) + "°C";
                    document.getElementById("target-extruder").innerText = "Ціль: " + data.telemetry.temps.extruder.target.toFixed(0) + "°C";
                    document.getElementById("temp-bed").innerText = data.telemetry.temps.bed.current.toFixed(1) + "°C";
                    document.getElementById("target-bed").innerText = "Ціль: " + data.telemetry.temps.bed.target.toFixed(0) + "°C";

                    const container = document.getElementById("dynamic-sensors-container");
                    const rawTelemetry = data.telemetry.raw_telemetry || {};

                    if (Object.keys(rawTelemetry).length === 0) {
                        container.innerHTML = '<p class="text-xs text-gray-500 text-center py-8">Немає додаткових активних датчиків.</p>';
                        return;
                    }

                    container.innerHTML = "";
                    
                    for (const [sensorName, sensorValue] of Object.entries(rawTelemetry)) {
                        const card = document.createElement("div");
                        card.className = "bg-gray-900 p-2.5 rounded border border-gray-800";

                        let html = `<p class="text-[11px] font-bold text-blue-400 border-b border-gray-800 pb-0.5 font-mono">${sensorName}</p>`;
                        
                        if (typeof sensorValue === "object" && sensorValue !== null) {
                            html += `<div class="grid grid-cols-1 sm:grid-cols-2 gap-x-3 gap-y-0.5 mt-1 text-[11px]">`;
                            for (const [propName, propValue] of Object.entries(sensorValue)) {
                                const displayValue = typeof propValue === "number" ? propValue.toFixed(1) : propValue;
                                html += `
                                    <div class="flex justify-between py-0.5 border-b border-gray-950">
                                        <span class="text-gray-500 font-mono text-[10px]">${propName}:</span>
                                        <span class="font-bold text-gray-300 font-mono text-[10px]">${displayValue}</span>
                                    </div>
                                `;
                            }
                            html += "</div>";
                        } else {
                            const displayValue = typeof sensorValue === "number" ? sensorValue.toFixed(1) : sensorValue;
                            html += `
                                <div class="flex justify-between text-[11px] mt-1">
                                    <span class="text-gray-500 font-mono text-[10px]">value:</span>
                                    <span class="font-bold text-gray-300 font-mono text-[10px]">${displayValue}</span>
                                </div>
                            `;
                        }

                        card.innerHTML = html;
                        container.appendChild(card);
                    }

                } catch (e) {
                    console.error("Помилка опитування статусу:", e);
                }
            }

            async function saveManualIP(ipAddress = null) {
                const ip = ipAddress || document.getElementById("manual-ip-input").value;
                if (!ip) return alert("Будь ласка, введіть коректну IP-адресу.");

                try {
                    const response = await secureFetch("/settings/printer-ip", {
                        method: "POST",
                        headers: {"Content-Type": "application/json"},
                        body: JSON.stringify({ip: ip})
                    });
                    const result = await response.json();
                    if (result.status === "success") {
                        alert("IP-адресу успішно збережено.");
                        document.getElementById("manual-ip-input").value = "";
                    }
                } catch (e) {
                    alert("Помилка збереження.");
                }
            }

            async function startScan() {
                const scanBtn = document.getElementById("scan-btn");
                const resultsDiv = document.getElementById("scan-results");
                const listDiv = document.getElementById("printers-list");

                scanBtn.innerText = "⏳ Йде сканування мережі (2 сек)...";
                scanBtn.disabled = true;

                try {
                    const response = await secureFetch("/settings/scan", { method: "POST" });
                    const data = await response.json();
                    
                    listDiv.innerHTML = "";
                    resultsDiv.classList.remove("hidden");

                    if (data.status === "success" && data.printers.length > 0) {
                        data.printers.forEach(printer => {
                            const item = document.createElement("div");
                            item.className = "flex items-center justify-between bg-gray-900 p-2 rounded text-xs";
                            item.innerHTML = `
                                <div>
                                    <span class="font-bold text-gray-200 block">${printer.name}</span>
                                    <span class="text-gray-500 font-mono">${printer.ip}:${printer.port}</span>
                                </div>
                                <button onclick="saveManualIP('${printer.ip}')" class="bg-emerald-600 hover:bg-emerald-500 px-3 py-1 rounded text-white font-bold transition">Підключити</button>
                            `;
                            listDiv.appendChild(item);
                        });
                    } else {
                        listDiv.innerHTML = '<p class="text-xs text-gray-500 p-2">Пристроїв не знайдено.</p>';
                    }
                } catch (e) {
                    alert("Помилка сканування.");
                } finally {
                    scanBtn.innerText = "🔍 Сканувати мережу";
                    scanBtn.disabled = false;
                }
            }

            checkAuthStatus();
        </script>
    </body>
    </html>
    """