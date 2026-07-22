import os
import time
import hashlib
import sqlite3
from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from core.database import DB_FILE

def parse_user_agent(ua_string: str) -> str:
    if not ua_string: return "Невідомий пристрій"
    ua_string = ua_string.lower()
    os_name = "Unknown OS"
    if "windows" in ua_string: os_name = "Windows"
    elif "android" in ua_string: os_name = "Android"
    elif "iphone" in ua_string or "ipad" in ua_string: os_name = "iOS"
    elif "macintosh" in ua_string or "mac os" in ua_string: os_name = "macOS"
    elif "linux" in ua_string: os_name = "Linux"
    
    browser_name = "Unknown Browser"
    if "vivaldi" in ua_string: browser_name = "Vivaldi"
    elif "yabrowser" in ua_string: browser_name = "Yandex Browser"
    elif "opr" in ua_string or "opera" in ua_string: browser_name = "Opera"
    elif "edg" in ua_string or "edge" in ua_string: browser_name = "Edge"
    elif "brave" in ua_string: browser_name = "Brave"
    elif "firefox" in ua_string: browser_name = "Firefox"
    elif "chrome" in ua_string: browser_name = "Chrome"
    elif "safari" in ua_string: browser_name = "Safari"
    return f"{browser_name} ({os_name})"

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
    except Exception: return False

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
    if not token: raise HTTPException(status_code=401, detail="Токен відсутній")
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, expires_at FROM sessions WHERE token=?", (token,))
    row = cursor.fetchone()
    conn.close()
    if not row: raise HTTPException(status_code=401, detail="Невірний токен")
    user_id, expires_at = row
    if time.time() > expires_at: raise HTTPException(status_code=401, detail="Сесія застаріла")
    return user_id

security_scheme = HTTPBearer()

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security_scheme)):
    return verify_session_token(credentials.credentials)