import asyncio
import json
import httpx
import websockets

class KlipperClient:
    def __init__(self, host: str = "", port: int = 7125):
        self.port = port
        self.active_ws = None  # Посилання на поточний активний WebSocket
        self.is_connected = False
        
        # Стан принтера за замовчуванням
        self.state = {
            "extruder_temp": 0.0,
            "extruder_target": 0.0,
            "bed_temp": 0.0,
            "bed_target": 0.0,
            "print_state": "not_configured"
        }
        
        if host:
            self.set_host(host)
        else:
            self.host = ""
            self.base_url = ""
            self.ws_url = ""

    def set_host(self, host: str):
        """Встановлення нової IP-адреси та шляхів підключення"""
        self.host = host
        self.base_url = f"http://{host}:{self.port}"
        self.ws_url = f"ws://{host}:{self.port}/websocket"

    async def update_host_and_reconnect(self, new_host: str):
        """Зміна адреси та миттєве примусове перепідключення"""
        self.set_host(new_host)
        if self.active_ws:
            # Закриваємо поточний сокет. Це викличе виняток у фоновому циклі,
            # і він автоматично почне підключатися вже до нового IP!
            await self.active_ws.close()
            print(f"[CLIENT] WebSocket закрито для перепідключення на {new_host}...")
        else:
            print(f"[CLIENT] Адресу оновлено на {new_host}. Очікуємо підключення...")

    async def send_gcode(self, gcode: str):
        if not self.host:
            return None
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/printer/gcode/script",
                    json={"script": gcode}
                )
                return response.json()
        except Exception as e:
            print(f"[HTTP ERROR] {e}")
            return None

    async def start_websocket_listener(self):
        """Нескінченний фоновий цикл зчитування даних"""
        while True:
            if not self.host:
                # Якщо хост ще не вказано в налаштуваннях, просто чекаємо
                self.state["print_state"] = "not_configured"
                self.is_connected = False
                await asyncio.sleep(2)
                continue

            try:
                print(f"Підключення до Moonraker WebSocket: {self.ws_url}...")
                async with websockets.connect(self.ws_url) as ws:
                    self.active_ws = ws
                    self.is_connected = True
                    self.state["print_state"] = "connected"
                    print("Успішно підключено до WebSocket!")

                    # Підписка на оновлення
                    subscribe_message = {
                        "jsonrpc": "2.0",
                        "method": "printer.objects.subscribe",
                        "params": {
                            "objects": {
                                "extruder": ["temperature", "target"],
                                "heater_bed": ["temperature", "target"],
                                "print_stats": ["state"]
                            }
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
                self.state["print_state"] = "disconnected"
                print(f"[WS DISCONNECTED] {e}. Повторна спроба за 5 сек...")
                await asyncio.sleep(5)

    def _parse_websocket_message(self, data: dict):
        if "result" in data and "status" in data["result"]:
            self._update_state(data["result"]["status"])
        elif data.get("method") == "notify_status_update":
            self._update_state(data["params"][0])

    def _update_state(self, status: dict):
        if "extruder" in status:
            self.state["extruder_temp"] = status["extruder"].get("temperature", self.state["extruder_temp"])
            self.state["extruder_target"] = status["extruder"].get("target", self.state["extruder_target"])
        if "heater_bed" in status:
            self.state["bed_temp"] = status["heater_bed"].get("temperature", self.state["bed_temp"])
            self.state["bed_target"] = status["heater_bed"].get("target", self.state["bed_target"])
        if "print_stats" in status:
            self.state["print_state"] = status["print_stats"].get("state", self.state["print_state"])