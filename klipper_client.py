import asyncio
import json
import httpx
import websockets
from base_client import BasePrinterClient

class KlipperClient(BasePrinterClient):
    def __init__(self, host: str = "", port: int = 7125):
        # Викликаємо конструктор батьківського класу BasePrinterClient
        super().__init__(host, port)
        if host:
            self.set_host(host)
        else:
            self.host = ""
            self.base_url = ""
            self.ws_url = ""
            print("[KLIPPER CLIENT] Ініціалізовано без хоста.")

    def set_host(self, host: str):
        self.host = host
        self.base_url = f"http://{host}:{self.port}"
        self.ws_url = f"ws://{host}:{self.port}/websocket"
        print(f"[KLIPPER CLIENT] Встановлено хост: {self.host} (REST: {self.base_url}, WS: {self.ws_url})")

    async def update_host_and_reconnect(self, new_host: str):
        print(f"[KLIPPER CLIENT] Отримано запит на зміну хоста на: {new_host}")
        self.set_host(new_host)
        if self.active_ws:
            print("[KLIPPER CLIENT] Закриваємо поточне з'єднання для перепідключення...")
            await self.active_ws.close()
        else:
            print("[KLIPPER CLIENT] Активного з'єднання немає, очікуємо автоматичного підключення.")

    async def get_all_configured_objects(self) -> list:
        if not self.host:
            return []
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.base_url}/printer/objects/list")
                if response.status_code == 200:
                    objects = response.json().get("result", {}).get("objects", [])
                    print(f"[KLIPPER CLIENT] Виявлено {len(objects)} об'єктів для зчитування.")
                    return objects
        except Exception as e:
            print(f"[KLIPPER CLIENT] Не вдалося зчитати список об'єктів: {e}")
        return []

    async def send_gcode(self, gcode: str) -> dict:
        if not self.host:
            return {"error": "No host configured"}
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/printer/gcode/script",
                    json={"script": gcode}
                )
                return response.json()
        except Exception as e:
            return {"error": str(e)}

    async def start_websocket_listener(self):
        print("[KLIPPER CLIENT] Фоновий процес WebSocket-слухача запущено.")
        while True:
            if not self.host:
                self.state["print_state"] = "not_configured"
                self.is_connected = False
                self.state["connected"] = False
                await asyncio.sleep(5)
                continue

            try:
                detected_objects = await self.get_all_configured_objects()
                print(f"[KLIPPER CLIENT WS] Спроба підключення до {self.ws_url}...")
                
                async with websockets.connect(self.ws_url, open_timeout=5) as ws:
                    self.active_ws = ws
                    self.is_connected = True
                    self.state["connected"] = True
                    print("[KLIPPER CLIENT WS] УСПІШНО підключено!")

                    # Динамічна підписка на всі виявлені об'єкти
                    subscription_objects = {obj: None for obj in detected_objects} if detected_objects else {
                        "extruder": None, "heater_bed": None, "print_stats": None
                    }

                    subscribe_message = {
                        "jsonrpc": "2.0",
                        "method": "printer.objects.subscribe",
                        "params": {
                            "objects": subscription_objects
                        },
                        "id": 1
                    }
                    await ws.send(json.dumps(subscribe_message))

                    async for message in ws:
                        data = json.loads(message)
                        self._parse_websocket_message(data)

            except Exception as e:
                self.is_connected = False
                self.active_ws = None
                self.state["connected"] = False
                self.state["print_state"] = "disconnected"
                print(f"[KLIPPER CLIENT WS ERROR] Помилка: {type(e).__name__} - {e}")
                print("[KLIPPER CLIENT WS] Повторна спроба підключення через 5 секунд...")
                await asyncio.sleep(5)

    def _parse_websocket_message(self, data: dict):
        if "result" in data and "status" in data["result"]:
            self._update_state(data["result"]["status"])
        elif data.get("method") == "notify_status_update":
            self._update_state(data["params"][0])

    def _update_state(self, status: dict):
        # 1. Записуємо "сирі" дані у raw_telemetry для нашого детального дебаг-монітора
        for key, value in status.items():
            if key not in self.state["raw_telemetry"]:
                self.state["raw_telemetry"][key] = {}
            if isinstance(value, dict):
                self.state["raw_telemetry"][key].update(value)
            else:
                self.state["raw_telemetry"][key] = value

        # 2. Мапимо основні дані в наш уніфікований стандарт
        if "extruder" in status:
            self.state["temps"]["extruder"]["current"] = status["extruder"].get("temperature", self.state["temps"]["extruder"]["current"])
            self.state["temps"]["extruder"]["target"] = status["extruder"].get("target", self.state["temps"]["extruder"]["target"])
            
        if "heater_bed" in status:
            self.state["temps"]["bed"]["current"] = status["heater_bed"].get("temperature", self.state["temps"]["bed"]["current"])
            self.state["temps"]["bed"]["target"] = status["heater_bed"].get("target", self.state["temps"]["bed"]["target"])
            
        if "print_stats" in status:
            self.state["print_state"] = status["print_stats"].get("state", self.state["print_state"])
            
        # Якщо увімкнено вентилятор обдування моделі
        if "fan" in status:
            self.state["fans"]["part_cooling"] = status["fan"].get("speed", 0.0) * 100

        # Якщо Klipper має датчик температури камери (chamber)
        for key, val in status.items():
            if "temperature_sensor" in key and "chamber" in key.lower():
                self.state["temps"]["chamber"]["current"] = val.get("temperature", self.state["temps"]["chamber"]["current"])

        print(f"[KLIPPER CLIENT STATE UPDATE] Оновлено уніфікований стан: {self.state}", flush=True)