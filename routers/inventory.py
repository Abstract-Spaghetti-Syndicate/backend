import sqlite3
import json
import httpx
from fastapi import APIRouter, HTTPException, Depends
from core.database import DB_FILE
from core.models import (
    SpoolmanImportRequest, 
    VendorCreateUpdate, LocationCreateUpdate, 
    FilamentCreateUpdate, SpoolCreateUpdate
)
from core.security import get_current_user

router = APIRouter(prefix="/api", tags=["Inventory"])

@router.get("/spools", dependencies=[Depends(get_current_user)])
def get_spools_list():
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT spool.id, vendor.name, filament.name, filament.material, 
                   COALESCE(spool.initial_weight, filament.weight, 1000.0) AS initial, 
                   spool.used_weight, filament.color_hex
            FROM spool
            JOIN filament ON spool.filament_id = filament.id
            JOIN vendor ON filament.vendor_id = vendor.id
            WHERE spool.archived = 0 ORDER BY spool.id DESC
        """)
        rows = cursor.fetchall()
        conn.close()
        
        spools = [{"id": r[0], "vendor": r[1], "name": r[2], "material": r[3], "initial_weight": r[4], "used_weight": r[5], "color_hex": r[6]} for r in rows]
        return {"status": "success", "spools": spools}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Помилка зчитування бази: {str(e)}")

@router.post("/spoolman/import", dependencies=[Depends(get_current_user)])
async def import_from_spoolman(payload: SpoolmanImportRequest):
    base_url = payload.spoolman_url.strip().rstrip("/")
    if not base_url.endswith("/api/v1"): base_url = f"{base_url}/api/v1"
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            v_resp = await client.get(f"{base_url}/vendor")
            if v_resp.status_code != 200: raise HTTPException(status_code=400)
            vendors = v_resp.json() if isinstance(v_resp.json(), list) else []
            
            f_resp = await client.get(f"{base_url}/filament")
            if f_resp.status_code != 200: raise HTTPException(status_code=400)
            filaments = f_resp.json() if isinstance(f_resp.json(), list) else []
            
            s_resp = await client.get(f"{base_url}/spool")
            if s_resp.status_code != 200: raise HTTPException(status_code=400)
            spools = s_resp.json() if isinstance(s_resp.json(), list) else []

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys = OFF")

        unique_locations = set(str(s.get("location")).strip() for s in spools if isinstance(s, dict) and s.get("location"))
        cursor.execute("DELETE FROM location") 
        for i, loc_name in enumerate(unique_locations, start=1):
            cursor.execute("INSERT INTO location (id, name, comment) VALUES (?, ?, ?)", (i, loc_name, "Імпортовано зі Spoolman"))

        for v in vendors:
            if isinstance(v, dict):
                cursor.execute("INSERT OR REPLACE INTO vendor (id, name, comment, deleted) VALUES (?, ?, ?, ?)", 
                               (v.get("id"), v.get("name"), v.get("comment"), 1 if v.get("deleted") else 0))
            
        for f in filaments:
            if isinstance(f, dict):
                v_id = f.get("vendor").get("id") if isinstance(f.get("vendor"), dict) else None
                cursor.execute("""
                    INSERT OR REPLACE INTO filament (id, name, vendor_id, material, price, density, diameter, weight, spool_weight, color_hex, comment, settings_extruder_temp, settings_bed_temp, deleted)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (f.get("id"), f.get("name"), v_id, f.get("material"), f.get("price"), f.get("density"), f.get("diameter"), f.get("weight"), f.get("spool_weight"), f.get("color_hex"), f.get("comment"), f.get("settings_extruder_temp"), f.get("settings_bed_temp"), 1 if f.get("deleted") else 0))

        for s in spools:
            if isinstance(s, dict):
                f_id = s.get("filament").get("id") if isinstance(s.get("filament"), dict) else None
                extra_val = json.dumps(s.get("extra")) if s.get("extra") else None
                cursor.execute("""
                    INSERT OR REPLACE INTO spool (id, filament_id, registered, first_used, last_used, initial_weight, spool_weight, used_weight, comment, archived, price, extra)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (s.get("id"), f_id, s.get("registered"), s.get("first_used"), s.get("last_used"), s.get("initial_weight"), s.get("spool_weight"), s.get("used_weight", 0.0), s.get("comment"), 1 if s.get("archived") else 0, s.get("price"), extra_val))

        cursor.execute("PRAGMA foreign_keys = ON")
        conn.commit()
        conn.close()
        
        return {"status": "success", "imported": {"vendors": len(vendors), "filaments": len(filaments), "spools": len(spools), "locations": len(unique_locations)}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/vendors", dependencies=[Depends(get_current_user)])
def get_vendors():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, comment FROM vendor WHERE deleted=0")
    rows = cursor.fetchall()
    conn.close()
    return {"status": "success", "vendors": [{"id": r[0], "name": r[1], "comment": r[2]} for r in rows]}

@router.get("/filaments", dependencies=[Depends(get_current_user)])
def get_filaments():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, material, vendor_id, diameter, density, color_hex, spool_weight, settings_extruder_temp, settings_bed_temp 
        FROM filament WHERE deleted=0
    """)
    rows = cursor.fetchall()
    conn.close()
    return {"status": "success", "filaments": [{"id": r[0], "name": r[1], "material": r[2], "vendor_id": r[3], "diameter": r[4] if r[4] is not None else 1.75, "density": r[5], "color_hex": r[6], "spool_weight": r[7], "ext_temp": r[8], "bed_temp": r[9]} for r in rows]}

@router.get("/locations", dependencies=[Depends(get_current_user)])
def get_locations():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, comment FROM location")
    rows = cursor.fetchall()
    conn.close()
    return {"status": "success", "locations": [{"id": r[0], "name": r[1], "comment": r[2]} for r in rows]}


# ==========================================
# CRUD ДЛЯ ВИРОБНИКІВ (VENDORS)
# ==========================================
@router.post("/vendors", dependencies=[Depends(get_current_user)])
def create_vendor(payload: VendorCreateUpdate):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO vendor (name, comment) VALUES (?, ?)", (payload.name, payload.comment))
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return {"status": "success", "id": new_id}

@router.put("/vendors/{item_id}", dependencies=[Depends(get_current_user)])
def update_vendor(item_id: int, payload: VendorCreateUpdate):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE vendor SET name=?, comment=?, deleted=? WHERE id=?", 
                   (payload.name, payload.comment, payload.deleted, item_id))
    conn.commit()
    conn.close()
    return {"status": "success"}

# ==========================================
# CRUD ДЛЯ ЛОКАЦІЙ (LOCATIONS)
# ==========================================
@router.post("/locations", dependencies=[Depends(get_current_user)])
def create_location(payload: LocationCreateUpdate):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO location (name, comment) VALUES (?, ?)", (payload.name, payload.comment))
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return {"status": "success", "id": new_id}

@router.put("/locations/{item_id}", dependencies=[Depends(get_current_user)])
def update_location(item_id: int, payload: LocationCreateUpdate):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE location SET name=?, comment=? WHERE id=?", 
                   (payload.name, payload.comment, item_id))
    conn.commit()
    conn.close()
    return {"status": "success"}

# ==========================================
# CRUD ДЛЯ ФІЛАМЕНТУ (FILAMENTS)
# ==========================================
@router.post("/filaments", dependencies=[Depends(get_current_user)])
def create_filament(payload: FilamentCreateUpdate):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO filament (name, vendor_id, material, price, density, diameter, 
        weight, spool_weight, color_hex, comment, settings_extruder_temp, settings_bed_temp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (payload.name, payload.vendor_id, payload.material, payload.price, payload.density, 
          payload.diameter, payload.weight, payload.spool_weight, payload.color_hex, 
          payload.comment, payload.settings_extruder_temp, payload.settings_bed_temp))
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return {"status": "success", "id": new_id}

@router.put("/filaments/{item_id}", dependencies=[Depends(get_current_user)])
def update_filament(item_id: int, payload: FilamentCreateUpdate):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE filament SET name=?, vendor_id=?, material=?, price=?, density=?, diameter=?, 
        weight=?, spool_weight=?, color_hex=?, comment=?, settings_extruder_temp=?, settings_bed_temp=?, deleted=?
        WHERE id=?
    """, (payload.name, payload.vendor_id, payload.material, payload.price, payload.density, 
          payload.diameter, payload.weight, payload.spool_weight, payload.color_hex, 
          payload.comment, payload.settings_extruder_temp, payload.settings_bed_temp, payload.deleted, item_id))
    conn.commit()
    conn.close()
    return {"status": "success"}

# ==========================================
# CRUD ДЛЯ КОТУШОК (SPOOLS)
# ==========================================
@router.post("/spools", dependencies=[Depends(get_current_user)])
def create_spool(payload: SpoolCreateUpdate):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO spool (filament_id, initial_weight, spool_weight, used_weight, price, comment)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (payload.filament_id, payload.initial_weight, payload.spool_weight, payload.used_weight, payload.price, payload.comment))
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return {"status": "success", "id": new_id}

@router.put("/spools/{item_id}", dependencies=[Depends(get_current_user)])
def update_spool(item_id: int, payload: SpoolCreateUpdate):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE spool SET filament_id=?, initial_weight=?, spool_weight=?, used_weight=?, price=?, comment=?, archived=?
        WHERE id=?
    """, (payload.filament_id, payload.initial_weight, payload.spool_weight, payload.used_weight, payload.price, payload.comment, payload.archived, item_id))
    conn.commit()
    conn.close()
    return {"status": "success"}