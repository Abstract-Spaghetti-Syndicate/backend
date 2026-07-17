import asyncio
import json
import httpx
import websockets

class KlipperClient:
    def __init__(self, host: str, port: int = 7125):
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self.ws_url = f"ws://{host}:{port}/websocket"
        
        # Асинхронний HTTP клієнт
        self.http_client = httpx.AsyncClient()
        self.is_connected = False
        
        # Внутрішній стан принтера, який ми будемо оновлювати
        self.state = {
            "extruder_temp": 0.0,
            "extruder_target": 0.0,
            "bed_temp": 0.0,
            "bed_target": 0.0,
            "print_state": "disconnected"
        }

    async def get_printer_info(self):
        """Отримання базової інформації про прошивку через HTTP REST API"""
        try:
            response = await self.http_client.get(f"{self.base_url}/printer/info")
            if response.status_code == 200:
                return response.json().get("result", {})
        except Exception as e:
            print(f"[HTTP ERROR] Не вдалося отримати інфо: {e}")
        return None

    async def send_gcode(self, gcode: str):
        """Відправка команди G-коду на принтер через HTTP POST"""
        try:
            response = await self.http_client.post(
                f"{self.base_url}/printer/gcode/script",
                json={"script": gcode}
            )
            return response.json()
        except Exception as e:
            print(f"[HTTP ERROR] Не вдалося відправити G-код: {e}")
            return None

    async def start_websocket_listener(self):
        """Запуск фонового прослуховувача WebSocket для збору телеметрії в реальному часі"""
        while True:
            try:
                print(f"Підключення до Moonraker WebSocket: {self.ws_url}...")
                async with websockets.connect(self.ws_url) as ws:
                    self.is_connected = True
                    self.state["print_state"] = "connected"
                    print("Успішно підключено до WebSocket!")

                    # 1. Надсилаємо запит на підписку до об'єктів Klipper
                    # Це стандартний JSON-RPC формат Moonraker
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

                    # 2. Слухаємо потік повідомлень від сервера
                    async for message in ws:
                        data = json.loads(message)
                        self._parse_websocket_message(data)

            except (websockets.exceptions.ConnectionClosed, OSError) as e:
                self.is_connected = False
                self.state["print_state"] = "disconnected"
                print(f"[WS DISCONNECTED] Втрата з'єднання: {e}. Повторна спроба за 5 секунд...")
                await asyncio.sleep(5)

    def _parse_websocket_message(self, data: dict):
        """Розбір повідомлень JSON-RPC, які приходять від Moonraker"""
        # Обробка первинної відповіді на підписку (повертає поточний повний стан)
        if "result" in data and "status" in data["result"]:
            status = data["result"]["status"]
            self._update_state(status)

        # Обробка періодичних оновлень статусу, коли дані змінюються (notify_status_update)
        elif data.get("method") == "notify_status_update":
            status_changes = data["params"][0]
            self._update_state(status_changes)

    def _update_state(self, status: dict):
        """Оновлення внутрішнього стану локальними значеннями"""
        if "extruder" in status:
            self.state["extruder_temp"] = status["extruder"].get("temperature", self.state["extruder_temp"])
            self.state["extruder_target"] = status["extruder"].get("target", self.state["extruder_target"])
        
        if "heater_bed" in status:
            self.state["bed_temp"] = status["heater_bed"].get("temperature", self.state["bed_temp"])
            self.state["bed_target"] = status["heater_bed"].get("target", self.state["bed_target"])

        if "print_stats" in status:
            self.state["print_state"] = status["print_stats"].get("state", self.state["print_state"])
        
        # Для дебагу ви можете розкоментувати рядок нижче, щоб бачити логи у терміналі:
        # print(f"[DEBUG STATE] {self.state}")