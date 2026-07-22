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