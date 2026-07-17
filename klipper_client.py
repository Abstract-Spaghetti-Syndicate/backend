import asyncio
import json
import httpx
import websockets

class KlipperClient:
    def __init__(self, host: str = "", port: int = 7125):
        self.port = port
        self.active_ws = None
        self.is_connected = False
        
        # Загальний динамічний стан принтера (буде заповнюватися автоматично)
        self.state = {}
        
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
        print(f"[KLIPPER CLIENT] Новий хост: {self.host}")

    async def update_host_and_reconnect(self, new_host: str):
        self.set_host(new_host)
        if self.active_ws:
            await self.active_ws.close()

    async def get_all_configured_objects(self) -> list:
        """Динамічно запитує список усіх об'єктів/датчиків, які підтримує принтер"""
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
            print(f"[KLIPPER CLIENT REST ERROR] G-код помилка: {e}")
            return None

    async def start_websocket_listener(self):
        print("[KLIPPER CLIENT] Фоновий слухач запущено.")
        while True:
            if not self.host:
                self.state = {"print_state": "not_configured"}
                self.is_connected = False
                await asyncio.sleep(3)
                continue

            try:
                # 1. Перед підключенням до WebSocket зчитуємо актуальний список об'єктів цього принтера
                detected_objects = await self.get_all_configured_objects()
                
                print(f"[KLIPPER CLIENT WS] Підключення до {self.ws_url}...")
                async with websockets.connect(self.ws_url, open_timeout=5) as ws:
                    self.active_ws = ws
                    self.is_connected = True
                    print("[KLIPPER CLIENT WS] УСПІШНО підключено!")

                    # 2. Динамічно будуємо запит підписки.
                    # Передаємо null замість списку атрибутів, що змушує Klipper повертати ВСІ параметри кожного об'єкта.
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
                    
                    print(f"[KLIPPER CLIENT WS] Динамічна підписка на {len(subscription_objects)} об'єктів...")
                    await ws.send(json.dumps(subscribe_message))

                    async for message in ws:
                        data = json.loads(message)
                        self._parse_websocket_message(data)

            except Exception as e:
                self.is_connected = False
                self.active_ws = None
                self.state = {"print_state": "disconnected"}
                print(f"[KLIPPER CLIENT WS ERROR] {type(e).__name__} - {e}. Перепідключення через 5 сек...")
                await asyncio.sleep(5)

    def _parse_websocket_message(self, data: dict):
        if "result" in data and "status" in data["result"]:
            self._update_state(data["result"]["status"])
        elif data.get("method") == "notify_status_update":
            self._update_state(data["params"][0])

    def _update_state(self, status: dict):
        """Універсальний динамічний парсер: зчитує будь-які ключі та значення без хардкоду"""
        updated = False
        for key, value in status.items():
            if key not in self.state:
                self.state[key] = {}
            
            # Якщо значення — словник, об'єднуємо нові дані зі старими
            if isinstance(value, dict):
                self.state[key].update(value)
            else:
                self.state[key] = value
            updated = True
            
        if updated:
            print(f"[KLIPPER CLIENT STATE UPDATE] Актуальний зліпок стану принтера: {self.state}", flush=True)