import asyncio
import httpx
from base_client import BasePrinterClient

class OctoPrintClient(BasePrinterClient):
    def __init__(self, host: str = "", port: int = 5000, api_key: str = ""):
        super().__init__(host, port)
        self.api_key = api_key
        if host:
            self.set_host(host)
        else:
            self.host = ""
            self.base_url = ""
            print("[OCTOPRINT CLIENT] Ініціалізовано без хоста.")

    def set_host(self, host: str):
        self.host = host
        self.base_url = f"http://{host}:{self.port}"
        print(f"[OCTOPRINT CLIENT] Новий хост: {self.host} (REST API: {self.base_url})")

    async def update_host_and_reconnect(self, new_host: str):
        print(f"[OCTOPRINT CLIENT] Запит на зміну хоста на: {new_host}")
        self.set_host(new_host)
        # Оскільки у нас HTTP-опитування (polling), перепідключати сокет не потрібно.
        # Наступний цикл сам надішле запит на нову адресу.

    async def send_gcode(self, gcode: str) -> dict:
        if not self.host or not self.api_key:
            return {"error": "Not configured"}
        try:
            headers = {"X-Api-Key": self.api_key}
            async with httpx.AsyncClient() as client:
                # В OctoPrint команди надсилаються на /api/printer/command
                response = await client.post(
                    f"{self.base_url}/api/printer/command",
                    json={"commands": [gcode]},
                    headers=headers
                )
                return {"status": "success", "status_code": response.status_code}
        except Exception as e:
            return {"error": str(e)}

    async def start_websocket_listener(self):
        """Фоновий процес опитування (HTTP Polling) замість WebSockets"""
        print("[OCTOPRINT CLIENT] Фоновий процес опитування OctoPrint запущено.")
        headers = {}
        
        while True:
            if not self.host or not self.api_key:
                self.state["print_state"] = "not_configured"
                self.is_connected = False
                self.state["connected"] = False
                await asyncio.sleep(5)
                continue

            headers["X-Api-Key"] = self.api_key
            
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    # 1. Запитуємо температури та загальний стан
                    p_resp = await client.get(f"{self.base_url}/api/printer", headers=headers)
                    # 2. Запитуємо статус поточного друку (назва файлу, прогрес)
                    j_resp = await client.get(f"{self.base_url}/api/job", headers=headers)

                if p_resp.status_code == 200:
                    self.is_connected = True
                    self.state["connected"] = True
                    p_data = p_resp.json()
                    
                    # Оновлюємо сирі дані для нашої дебаг-панелі
                    self.state["raw_telemetry"] = p_data
                    
                    # Інтегруємо дані про роботу
                    if j_resp.status_code == 200:
                        j_data = j_resp.json()
                        self.state["raw_telemetry"]["job"] = j_data
                        self.state["print_state"] = j_data.get("state", "unknown").lower()
                    else:
                        self.state["print_state"] = p_data.get("state", {}).get("text", "unknown").lower()

                    # Мапимо дані в наш Уніфікований Стандарт (self.state)
                    temps = p_data.get("temperature", {})
                    
                    # OctoPrint називає сопло як "tool0"
                    if "tool0" in temps:
                        self.state["temps"]["extruder"]["current"] = temps["tool0"].get("actual", self.state["temps"]["extruder"]["current"])
                        self.state["temps"]["extruder"]["target"] = temps["tool0"].get("target", self.state["temps"]["extruder"]["target"])
                    
                    if "bed" in temps:
                        self.state["temps"]["bed"]["current"] = temps["bed"].get("actual", self.state["temps"]["bed"]["current"])
                        self.state["temps"]["bed"]["target"] = temps["bed"].get("target", self.state["temps"]["bed"]["target"])

                    print(f"[OCTOPRINT CLIENT STATE UPDATE] Оновлено уніфікований стан: {self.state}", flush=True)
                else:
                    self.is_connected = False
                    self.state["connected"] = False
                    self.state["print_state"] = "auth_error"
                    print(f"[OCTOPRINT CLIENT ERROR] Помилка ключа API. Статус: {p_resp.status_code}", flush=True)

            except Exception as e:
                self.is_connected = False
                self.state["connected"] = False
                self.state["print_state"] = "disconnected"
                print(f"[OCTOPRINT CLIENT WS ERROR] Помилка: {type(e).__name__} - {e}. Повтор...", flush=True)

            # Опитуємо OctoPrint кожні 1.5 секунди
            await asyncio.sleep(1.5)