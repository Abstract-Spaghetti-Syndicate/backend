from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import asyncio
from klipper_client import KlipperClient

# Створюємо клієнт. Замініть "192.168.1.100" на реальний локальний IP вашого принтера з Klipper.
# Якщо у вас зараз немає увімкненого принтера під рукою, клієнт просто буде безпечно намагатися підключитися кожні 5 сек.
KLIPPER_HOST = "192.168.1.100" 
klipper = KlipperClient(host=KLIPPER_HOST)

# Схема для валідації запиту відправки G-коду
class GCodeRequest(BaseModel):
    command: str

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Код тут виконується ПРИ СТАРТІ сервера:
    # Запускаємо нескінченний слухач WebSocket у фоновому таску asyncio
    listener_task = asyncio.create_task(klipper.start_websocket_listener())
    
    yield  # Тут FastAPI запускається і починає приймати запити від користувачів
    
    # Код тут виконується ПРИ ЗУПИНЦІ сервера:
    listener_task.cancel()  # Зупиняємо фоновий таск
    await klipper.http_client.aclose()  # Закриваємо сесію HTTP клієнта
    print("Сервер зупинено, ресурси звільнено.")

# Створюємо додаток із життєвим циклом lifespan
app = FastAPI(title="3D Printer API Gateway", lifespan=lifespan)

@app.get("/printer/status")
async def get_printer_status():
    """Фронтенд буде викликати цей ендпоінт, щоб миттєво отримати актуальний стан принтера"""
    return {
        "connected": klipper.is_connected,
        "telemetry": klipper.state
    }

@app.get("/printer/info")
async def get_printer_system_info():
    """Ендпоінт для отримання версії прошивки Klipper"""
    info = await klipper.get_printer_info()
    if not info:
        raise HTTPException(status_code=503, detail="Не вдалося зв'язатися з принтером по HTTP")
    return info

@app.post("/printer/gcode")
async def execute_gcode(payload: GCodeRequest):
    """Ендпоінт для відправки команд принтеру (наприклад, G28 для автохоуму)"""
    if not klipper.is_connected:
        raise HTTPException(status_code=503, detail="Принтер не підключений")
    
    result = await klipper.send_gcode(payload.command)
    return result