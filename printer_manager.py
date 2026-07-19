import sqlite3
import asyncio
import os
from klipper_client import KlipperClient
from octoprint_client import OctoPrintClient
from reprap_client import RepRapClient

# Динамічно визначаємо абсолютний шлях до нашої бази даних
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "data", "settings.db")

class PrinterManager:
    def __init__(self):
        self.clients = {}  # {printer_id (int): client_instance}
        self.tasks = {}    # {printer_id (int): asyncio.Task}

    def load_all_printers(self):
        print("[PRINTER MANAGER] Початок завантаження принтерів з бази...", flush=True)
        
        # Переконуємося, що файл бази даних фізично існує
        if not os.path.exists(DB_FILE):
            print("[PRINTER MANAGER] База даних ще не створена. Очікуємо ініціалізації при старті сервера.", flush=True)
            return

        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, type, host, port, api_key FROM printers")
            rows = cursor.fetchall()
            conn.close()

            for row in rows:
                p_id, name, p_type, host, port, api_key = row
                self.start_printer_client(p_id, p_type, host, port, api_key)
                
            print(f"[PRINTER MANAGER] Успішно запущено клієнтів: {len(self.clients)}", flush=True)
        except sqlite3.OperationalError as e:
            print(f"[PRINTER MANAGER WARNING] Спроба зчитування не вдалася (можливо база ще чиста): {e}", flush=True)

    def start_printer_client(self, p_id: int, p_type: str, host: str, port: int, api_key: str):
        if p_type == "klipper":
            client = KlipperClient(host=host, port=port)
        elif p_type == "octoprint":
            client = OctoPrintClient(host=host, port=port, api_key=api_key)
        elif p_type == "reprap":
            # Для RepRap api_key виступає в ролі пароля до плати (якщо він є)
            client = RepRapClient(host=host, port=port, password=api_key)
        else:
            print(f"[PRINTER MANAGER ERROR] Невідомий тип принтера '{p_type}' для ID #{p_id}", flush=True)
            return

        self.clients[p_id] = client
        task = asyncio.create_task(client.start_websocket_listener())
        self.tasks[p_id] = task
        print(f"[PRINTER MANAGER] Запущено фоновий таск для принтера #{p_id} ({p_type})", flush=True)

    async def stop_printer_client(self, p_id: int):
        if p_id in self.tasks:
            self.tasks[p_id].cancel()
            del self.tasks[p_id]
        if p_id in self.clients:
            if self.clients[p_id].active_ws:
                await self.clients[p_id].active_ws.close()
            del self.clients[p_id]
        print(f"[PRINTER MANAGER] Роботу з принтером #{p_id} успішно зупинено.", flush=True)

    async def shutdown(self):
        for p_id in list(self.tasks.keys()):
            await self.stop_printer_client(p_id)
        print("[PRINTER MANAGER] Усі фонові таски успішно звільнено.", flush=True)