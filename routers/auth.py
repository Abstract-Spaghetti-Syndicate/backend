import sqlite3
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials

from core.database import DB_FILE
from core.models import RegisterRequest, LoginRequest, RevokeRequest
from core.security import (
    hash_password, verify_password, create_session, 
    verify_session_token, parse_user_agent, get_current_user, security_scheme
)

router = APIRouter(prefix="/api/auth", tags=["Auth"])

@router.get("/status")
def get_auth_status():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    count = cursor.fetchone()[0]
    conn.close()
    return {"is_registered": count > 0}

@router.post("/register")
def register_user(payload: RegisterRequest, request: Request):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] > 0:
        conn.close()
        raise HTTPException(status_code=400, detail="Реєстрація закрита.")
    
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

@router.post("/login")
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

@router.get("/sessions")
def get_active_sessions(credentials: HTTPAuthorizationCredentials = Depends(security_scheme)):
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

@router.post("/sessions/revoke")
def revoke_session(payload: RevokeRequest, credentials: HTTPAuthorizationCredentials = Depends(security_scheme)):
    current_token = credentials.credentials
    verify_session_token(current_token)
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sessions WHERE token=?", (payload.token,))
    conn.commit()
    conn.close()
    return {"status": "success"}