import asyncio
import httpx
from base_client import BasePrinterClient

class RepRapClient(BasePrinterClient):
    def __init__(self, host: str = "", port: int = 80, password: str = ""):
        super().__init__(host, port)
        self.password = password
        self.session_connected = False
        if host:
            self.set_host(host)
        else:
            self.host = ""
            self.base_url = ""
            print("[REPRAP CLIENT] Ініціалізовано без хоста.")

    def set_host(self, host: str):
        self.host = host
        # За замовчуванням Duet працює на порті 80
        self.base_url = f"http://{host}:{self.port}"
        print(f"[REPRAP CLIENT] Новий хост: {self.host} (REST API: {self.base_url})")

    async def update_host_and_reconnect(self, new_host: str):
        print(f"[REPRAP CLIENT] Запит на зміну хоста на: {new_host}")
        self.set_host(new_host)
        self.session_connected = False

    async def send_gcode(self, gcode: str) -> dict:
        if not self.host:
            return {"error": "Not configured"}
        try:
            async with httpx.AsyncClient() as client:
                # В RRF команди надсилаються через GET/POST на /rr_gcode
                response = await client.get(
                    f"{self.base_url}/rr_gcode",
                    params={"gcode": gcode},
                    timeout=5.0
                )
                return {"status": "success", "status_code": response.status_code, "response": response.text}
        except Exception as e:
            return {"error": str(e)}

    async def start_websocket_listener(self):
        """Фоновий процес HTTP-опитування RepRapFirmware"""
        print("[REPRAP CLIENT] Фоновий процес опитування RepRapFirmware запущено.")
        
        while True:
            if not self.host:
                self.state["print_state"] = "not_configured"
                self.is_connected = False
                self.state["connected"] = False
                await asyncio.sleep(5)
                continue

            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    # 1. Авторизація за паролем (якщо він заданий у налаштуваннях)
                    if not self.session_connected and self.password:
                        try:
                            conn_resp = await client.get(
                                f"{self.base_url}/rr_connect", 
                                params={"password": self.password}
                            )
                            if conn_resp.status_code == 200:
                                self.session_connected = True
                        except Exception:
                            # Продовжуємо без сесії, якщо плата відкрита без пароля
                            pass
                    
                    # 2. Опитуємо всю Object Model
                    response = await client.get(f"{self.base_url}/rr_model")

                if response.status_code == 200:
                    self.is_connected = True
                    self.state["connected"] = True
                    data = response.json()
                    
                    # Зберігаємо "сиру" телеметрію для дебаг-панелі
                    self.state["raw_telemetry"] = data
                    
                    # Деякі версії повертають об'єкт у полі "result", деякі - відразу в корені
                    result = data.get("result", {}) if "result" in data else data
                    
                    # --- ПАРСИНГ СТАТУСУ ---
                    state_obj = result.get("state", {})
                    status_str = state_obj.get("status", "idle").lower()
                    
                    # Мапимо специфічні стани RRF в уніфікований стандарт
                    if status_str in ["processing", "simulating"]:
                        self.state["print_state"] = "printing"
                    elif status_str in ["paused", "pausing"]:
                        self.state["print_state"] = "paused"
                    else:
                        self.state["print_state"] = status_str

                    # --- ПАРСИНГ ТЕМПЕРАТУР ---
                    heat_obj = result.get("heat", {})
                    heaters = heat_obj.get("heaters", [])
                    
                    # Для стандартних RRF конфігурацій:
                    # Heater 0 -> стіл (heater_bed)
                    # Heater 1 -> перший хотенд (extruder)
                    if len(heaters) > 0:
                        bed_heater = heaters[0]
                        self.state["temps"]["bed"]["current"] = bed_heater.get("current", 0.0)
                        
                        bed_state = bed_heater.get("state", "off").lower()
                        if bed_state == "active":
                            self.state["temps"]["bed"]["target"] = bed_heater.get("active", 0.0)
                        elif bed_state == "standby":
                            self.state["temps"]["bed"]["target"] = bed_heater.get("standby", 0.0)
                        else:
                            self.state["temps"]["bed"]["target"] = 0.0
                            
                    if len(heaters) > 1:
                        ext_heater = heaters[1]
                        self.state["temps"]["extruder"]["current"] = ext_heater.get("current", 0.0)
                        
                        ext_state = ext_heater.get("state", "off").lower()
                        if ext_state == "active":
                            self.state["temps"]["extruder"]["target"] = ext_heater.get("active", 0.0)
                        elif ext_state == "standby":
                            self.state["temps"]["extruder"]["target"] = ext_heater.get("standby", 0.0)
                        else:
                            self.state["temps"]["extruder"]["target"] = 0.0

                    # --- ПАРСИНГ ОБДУВУ ---
                    fans = result.get("fans", [])
                    if len(fans) > 0:
                        # actualValue в RRF лежить в діапазоні 0.0-1.0, множимо на 100
                        self.state["fans"]["part_cooling"] = fans[0].get("actualValue", 0.0) * 100

                    print(f"[REPRAP CLIENT STATE UPDATE] Оновлено стан: {self.state}", flush=True)
                else:
                    self.is_connected = False
                    self.state["connected"] = False
                    self.state["print_state"] = "disconnected"

            except Exception as e:
                self.is_connected = False
                self.state["connected"] = False
                self.state["print_state"] = "disconnected"
                print(f"[REPRAP CLIENT ERROR] Помилка: {type(e).__name__} - {e}. Повтор...", flush=True)

            # Робимо паузу 1.5 секунди перед наступним опитуванням
            await asyncio.sleep(1.5)