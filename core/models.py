from pydantic import BaseModel
from typing import Optional

class RenamePrinterRequest(BaseModel):
    name: str

class RegisterRequest(BaseModel):
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class IPRequest(BaseModel):
    ip: str
    type: str = "klipper"      
    api_key: str = ""          
    name: str = "Default Printer" 

class RevokeRequest(BaseModel):
    token: str

class SpoolmanImportRequest(BaseModel):
    spoolman_url: str

class NewPrinterRequest(BaseModel):
    name: str
    type: str
    host: str
    port: int
    api_key: Optional[str] = None

# --- ДОДАТИ В КІНЕЦЬ ФАЙЛУ core/models.py ---

class VendorCreateUpdate(BaseModel):
    name: str
    comment: Optional[str] = None
    deleted: int = 0

class LocationCreateUpdate(BaseModel):
    name: str
    comment: Optional[str] = None

class FilamentCreateUpdate(BaseModel):
    name: Optional[str] = None
    vendor_id: Optional[int] = None
    material: Optional[str] = None
    price: Optional[float] = None
    density: float = 1.24
    diameter: float = 1.75
    weight: Optional[float] = 1000.0
    spool_weight: Optional[float] = 200.0
    color_hex: Optional[str] = None
    comment: Optional[str] = None
    settings_extruder_temp: Optional[int] = None
    settings_bed_temp: Optional[int] = None
    deleted: int = 0

class SpoolCreateUpdate(BaseModel):
    filament_id: int
    initial_weight: Optional[float] = None
    spool_weight: Optional[float] = None
    used_weight: float = 0.0
    price: Optional[float] = None
    comment: Optional[str] = None
    archived: int = 0