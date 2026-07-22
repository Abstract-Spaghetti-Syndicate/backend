import sqlite3
from fastapi import APIRouter, HTTPException, Depends, Request
from core.database import DB_FILE, save_ip_to_db
from core.models import RenamePrinterRequest, NewPrinterRequest, IPRequest
from core.security import get_current_user
from core.network_scanner import scan_network_for_printers_tcp

router = APIRouter(tags=["Printers"])

@router.get("/api/printers", dependencies=[Depends(get_current_user)])
def get_printers_list():
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, type, host, port FROM printers ORDER BY id ASC")
        rows = cursor.fetchall()
        conn.close()
        
        printers = [{"id": r[0], "name": r[1], "type": r[2], "host": r[3], "port": r[4]} for r in rows]
        return {"status": "success", "printers": printers}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Помилка: {e}")

@router.put("/api/printers/{printer_id}/rename", dependencies=[Depends(get_current_user)])
async def rename_printer(printer_id: int, payload: RenamePrinterRequest):
    new_name = payload.name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="Назва не може бути порожньою")
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE printers SET name=? WHERE id=?", (new_name, printer_id))
    if cursor.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Принтер не знайдено")
        
    conn.commit()
    conn.close()
    return {"status": "success", "new_name": new_name}

@router.post("/api/printers", dependencies=[Depends(get_current_user)])
async def add_new_printer(payload: NewPrinterRequest, request: Request):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO printers (name, type, host, port, api_key) VALUES (?, ?, ?, ?, ?)",
        (payload.name, payload.type, payload.host, payload.port, payload.api_key)
    )
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    
    manager = request.app.state.manager
    manager.start_printer_client(new_id, payload.type, payload.host, payload.port, payload.api_key)
    return {"status": "success", "printer_id": new_id}

@router.get("/api/printers/{printer_id}/status", dependencies=[Depends(get_current_user)])
async def get_printer_status(printer_id: int, request: Request):
    manager = request.app.state.manager
    client = manager.clients.get(printer_id)
    if not client:
        raise HTTPException(status_code=404, detail="Принтер не знайдено або він не запущений")
    return {
        "printer_id": printer_id,
        "connected": client.is_connected,
        "telemetry": client.state
    }

# --- ШАР СУМІСНОСТІ З ТЕСТОВИМ UI ---
@router.get("/printer/status", dependencies=[Depends(get_current_user)])
async def get_status_compatibility(request: Request):
    manager = request.app.state.manager
    if not manager.clients:
        return {
            "configured_ip": "Не налаштовано",
            "connected": False,
            "telemetry": {
                "temps": {"extruder": {"current": 0.0, "target": 0.0}, "bed": {"current": 0.0, "target": 0.0}, "chamber": {"current": 0.0, "target": 0.0}},
                "fans": {"part_cooling": 0.0},
                "print_state": "not_configured",
                "raw_telemetry": {}
            }
        }
    first_id = list(manager.clients.keys())[0]
    client = manager.clients[first_id]
    return {"configured_ip": client.host, "connected": client.is_connected, "telemetry": client.state}

@router.post("/settings/printer-ip", dependencies=[Depends(get_current_user)])
async def update_printer_ip_compatibility(payload: IPRequest, request: Request):
    ip = payload.ip.strip()
    p_type = payload.type.strip().lower()
    api_key = payload.api_key.strip() if payload.api_key else ""
    name = payload.name.strip() if payload.name else "Default Printer"
    
    if not ip: raise HTTPException(status_code=400, detail="IP не може бути пустим")
    save_ip_to_db(ip)
    
    host, port = ip, 80
    if p_type == "klipper": port = 7125
    elif p_type == "octoprint": port = 5000

    if ":" in ip:
        try:
            host, port_str = ip.split(":")
            port = int(port_str)
        except Exception: pass

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM printers WHERE name=?", (name,))
    row = cursor.fetchone()
    
    manager = request.app.state.manager
    if row:
        p_id = row[0]
        cursor.execute("UPDATE printers SET type=?, host=?, port=?, api_key=? WHERE id=?", (p_type, host, port, api_key, p_id))
        conn.commit()
        if p_id in manager.clients:
            await manager.stop_printer_client(p_id)
        manager.start_printer_client(p_id, p_type, host, port, api_key)
    else:
        cursor.execute("INSERT INTO printers (name, type, host, port, api_key) VALUES (?, ?, ?, ?, ?)", (name, p_type, host, port, api_key))
        conn.commit()
        new_id = cursor.lastrowid
        manager.start_printer_client(new_id, p_type, host, port, api_key)
        
    conn.close()
    return {"status": "success", "saved_ip": ip, "type": p_type, "name": name}

@router.post("/settings/scan", dependencies=[Depends(get_current_user)])
async def scan_printers():
    found = await scan_network_for_printers_tcp()
    return {"status": "success", "printers": found}