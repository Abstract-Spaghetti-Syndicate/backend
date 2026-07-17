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
            print("[KLIPPER CLIENT] Ініціалізовано без хоста (принтер ще не налаштовано).")

    def set_host(self, host: str):
        """Встановлення нової IP-адреси та шляхів підключення"""
        self.host = host
        self.base_url = f"http://{host}:{self.port}"
        self.ws_url = f"ws://{host}:{self.port}/websocket"
        print(f"[KLIPPER CLIENT] Встановлено нову адресу принтера: {self.host} (REST: {self.base_url}, WS: {self.ws_url})")

    async def update_host_and_reconnect(self, new_host: str):
        """Зміна адреси та миттєве примусове перепідключення"""
        print(f"[KLIPPER CLIENT] Отримано запит на зміну хоста на: {new_host}")
        self.set_host(new_host)
        if self.active_ws:
            print("[KLIPPER CLIENT] Закриваємо активне з'єднання для перепідключення...")
            await self.active_ws.close()
        else:
            print("[KLIPPER CLIENT] Активного з'єднання немає, очікуємо фонового автоматичного підключення.")

    async def send_gcode(self, gcode: str):
        if not self.host:
            print("[KLIPPER CLIENT] Помилка: Спроба відправити G-код, але хост не налаштований.")
            return None
        try:
            print(f"[KLIPPER CLIENT] Відправка G-коду: {gcode}")
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/printer/gcode/script",
                    json={"script": gcode}
                )
                print(f"[KLIPPER CLIENT] REST відповідь: Status={response.status_code}, Body={response.text}")
                return response.json()
        except Exception as e:
            print(f"[KLIPPER CLIENT REST ERROR] Помилка відправки G-коду: {type(e).__name__} - {e}")
            return None

    async def start_websocket_listener(self):
        """Нескінченний фоновий цикл зчитування даних"""
        print("[KLIPPER CLIENT] Фоновий процес WebSocket-слухача запущено.")
        while True:
            if not self.host:
                self.state["print_state"] = "not_configured"
                self.is_connected = False
                await asyncio.sleep(5)
                continue

            try:
                print(f"[KLIPPER CLIENT WS] Спроба підключення до {self.ws_url}...")
                async with websockets.connect(self.ws_url, open_timeout=5) as ws:
                    self.active_ws = ws
                    self.is_connected = True
                    self.state["print_state"] = "connected"
                    print("[KLIPPER CLIENT WS] УСПІШНО підключено!")

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
                    print(f"[KLIPPER CLIENT WS] Надсилаємо запит підписки: {subscribe_message}")
                    await ws.send(json.dumps(subscribe_message))

                    async for message in ws:
                        data = json.loads(message)
                        self._parse_websocket_message(data)

            except Exception as e:
                self.is_connected = False
                self.active_ws = None
                self.state["print_state"] = "disconnected"
                print(f"[KLIPPER CLIENT WS ERROR] Помилка: {type(e).__name__} - {e}")
                print("[KLIPPER CLIENT WS] Повторна спроба підключення через 5 секунд...")
                await asyncio.sleep(5)

    def _parse_websocket_message(self, data: dict):
        if "result" in data and "status" in data["result"]:
            print(f"[KLIPPER CLIENT WS] Отримано первинний стан: {data['result']['status']}")
            self._update_state(data["result"]["status"])
        elif data.get("method") == "notify_status_update":
            # Якщо хочете бачити логи кожної секунди — розкоментуйте рядок нижче:
            # print(f"[KLIPPER CLIENT WS] Телеметрія: {data['params'][0]}")
            self._update_state(data["params"][0])

    def _update_state(self, status: dict):
        updated = False
        if "extruder" in status:
            self.state["extruder_temp"] = status["extruder"].get("temperature", self.state["extruder_temp"])
            self.state["extruder_target"] = status["extruder"].get("target", self.state["extruder_target"])
            updated = True
        if "heater_bed" in status:
            self.state["bed_temp"] = status["heater_bed"].get("temperature", self.state["bed_temp"])
            self.state["bed_target"] = status["heater_bed"].get("target", self.state["bed_target"])
            updated = True
        if "print_stats" in status:
            self.state["print_state"] = status["print_stats"].get("state", self.state["print_state"])
            updated = True
        if updated:
            print(f"[KLIPPER CLIENT STATE UPDATE] Поточний локальний стан: {self.state}")