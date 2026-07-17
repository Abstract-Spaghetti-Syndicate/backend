import sqlite3
import socket
import time
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from zeroconf import Zeroconf, ServiceBrowser, ServiceListener
from klipper_client import KlipperClient

# --- Робота з базою даних SQLite ---
def init_db():
    conn = sqlite3.connect("settings.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.commit()
    conn.close()

def get_saved_ip() -> str:
    conn = sqlite3.connect("settings.db")
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key='printer_ip'")
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else ""

def save_ip_to_db(ip: str):
    conn = sqlite3.connect("settings.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('printer_ip', ?)", (ip,))
    conn.commit()
    conn.close()


# --- Реалізація Автопошуку mDNS (Zeroconf) ---
class MoonrakerListener(ServiceListener):
    def __init__(self):
        self.printers = []

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        info = zc.get_service_info(type_, name)
        if info:
            # Конвертуємо байти IP-адреси у текстовий формат (наприклад, 192.168.1.5)
            addresses = [socket.inet_ntoa(addr) for addr in info.addresses]
            self.printers.append({
                "name": name.split('.')[0],
                "ip": addresses[0] if addresses else "unknown",
                "port": info.port
            })

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        pass

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        pass

def scan_network_for_printers() -> list:
    zc = Zeroconf()
    listener = MoonrakerListener()
    # Шукаємо пристрої, які оголошують сервіс Moonraker/Klipper
    browser = ServiceBrowser(zc, "_moonraker._tcp.local.", listener)
    time.sleep(2.0)  # Даємо сканеру 2 секунди, щоб зібрати відповіді в мережі
    zc.close()
    return listener.printers


# --- Ініціалізація клієнта з бази даних ---
init_db()
saved_ip = get_saved_ip()
klipper = KlipperClient(host=saved_ip)


# --- Життєвий цикл FastAPI ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Старт фонового процесу підключення
    listener_task = asyncio.create_task(klipper.start_websocket_listener())
    yield
    # Завершення роботи
    listener_task.cancel()
    await klipper.http_client.aclose()

app = FastAPI(title="Klipper Smart Gateway", lifespan=lifespan)


# --- Моделі даних ---
class IPRequest(BaseModel):
    ip: str


# --- Спеціальні API Ендпоінти ---

@app.get("/printer/status")
async def get_status():
    """Повертає поточний статус і телеметрію"""
    return {
        "configured_ip": klipper.host,
        "connected": klipper.is_connected,
        "telemetry": klipper.state
    }

@app.post("/settings/printer-ip")
async def update_printer_ip(payload: IPRequest):
    """Спосіб 1: Зберегти IP в базу та перепідключитися"""
    ip = payload.ip.strip()
    if not ip:
        raise HTTPException(status_code=400, detail="IP не може бути пустим")
    
    save_ip_to_db(ip)  # Зберігаємо в SQLite
    await klipper.update_host_and_reconnect(ip)  # Даємо команду клієнту
    return {"status": "success", "saved_ip": ip}

@app.post("/settings/scan")
def scan_printers():
    """Спосіб 2: Автоматичний пошук принтерів у мережі"""
    try:
        found = scan_network_for_printers()
        return {"status": "success", "printers": found}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Помилка сканування: {str(e)}")


# --- Візуальний інтерфейс (HTML + JS) ---
@app.get("/", response_class=HTMLResponse)
def get_home_page():
    return """
    <!DOCTYPE html>
    <html lang="uk">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Filament & Printer Hub</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-gray-900 text-gray-100 font-sans min-h-screen">
        <div class="container mx-auto p-6 max-w-4xl">
            <!-- Header -->
            <header class="mb-8 text-center">
                <h1 class="text-3xl font-extrabold text-blue-500">Abstract Spaghetti Syndicate</h1>
                <p class="text-gray-400 mt-2">Панель керування та налаштування принтера</p>
            </header>

            <!-- Grid Layout -->
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                
                <!-- Ліва колонка: Статус принтера -->
                <div class="bg-gray-800 p-6 rounded-lg shadow-lg border border-gray-700">
                    <h2 class="text-xl font-bold mb-4 border-b border-gray-700 pb-2">Монітор принтера</h2>
                    <div class="space-y-4">
                        <div>
                            <span class="text-gray-400">Налаштований IP:</span>
                            <span id="current-ip" class="font-mono text-blue-400 block">Завантаження...</span>
                        </div>
                        <div>
                            <span class="text-gray-400">Статус:</span>
                            <span id="connection-status" class="px-2 py-1 rounded text-xs font-bold bg-gray-700 text-gray-300">...</span>
                        </div>
                        <div class="grid grid-cols-2 gap-4 mt-4">
                            <div class="bg-gray-900 p-4 rounded text-center">
                                <p class="text-xs text-gray-500">Екструдер</p>
                                <p id="temp-extruder" class="text-2xl font-bold text-red-500">0.0°C</p>
                                <p id="target-extruder" class="text-xs text-gray-400">Ціль: 0°C</p>
                            </div>
                            <div class="bg-gray-900 p-4 rounded text-center">
                                <p class="text-xs text-gray-500">Стіл</p>
                                <p id="temp-bed" class="text-2xl font-bold text-yellow-500">0.0°C</p>
                                <p id="target-bed" class="text-xs text-gray-400">Ціль: 0°C</p>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Права колонка: Налаштування підключення -->
                <div class="space-y-6">
                    
                    <!-- Спосіб 1: Ручне введення та збереження у базу даних -->
                    <div class="bg-gray-800 p-6 rounded-lg shadow-lg border border-gray-700">
                        <h2 class="text-lg font-bold text-white mb-2">Спосіб 1: Зберегти IP у базу (SQLite)</h2>
                        <p class="text-xs text-gray-400 mb-4">Введіть IP вручну. Він запишеться у локальну базу даних.</p>
                        <div class="flex gap-2">
                            <input id="manual-ip-input" type="text" placeholder="напр. 192.168.1.115" class="bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm flex-1 focus:outline-none focus:border-blue-500 text-mono">
                            <button onclick="saveManualIP()" class="bg-blue-600 hover:bg-blue-500 text-white text-sm font-bold px-4 py-2 rounded transition">Зберегти</button>
                        </div>
                    </div>

                    <!-- Спосіб 2: Автоматичний mDNS пошук у мережі -->
                    <div class="bg-gray-800 p-6 rounded-lg shadow-lg border border-gray-700">
                        <h2 class="text-lg font-bold text-white mb-2">Спосіб 2: Автоматичний пошук (mDNS)</h2>
                        <p class="text-xs text-gray-400 mb-4">Сканувати домашню мережу на наявність Klipper/Moonraker принтерів.</p>
                        <button id="scan-btn" onclick="startScan()" class="w-full bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-bold py-2 px-4 rounded transition">🔍 Сканувати мережу</button>
                        
                        <!-- Список знайдених пристроїв -->
                        <div id="scan-results" class="mt-4 space-y-2 hidden">
                            <p class="text-xs font-semibold text-gray-400 border-b border-gray-700 pb-1">Знайдені пристрої:</p>
                            <div id="printers-list" class="max-h-40 overflow-y-auto space-y-2">
                                <!-- Сюди будуть додаватися принтери через JS -->
                            </div>
                        </div>
                    </div>

                </div>
            </div>
        </div>

        <script>
            // Регулярне опитування статусу принтера (кожні 1.5 секунди)
            async function pollStatus() {
                try {
                    const response = await fetch('/printer/status');
                    const data = await response.json();
                    
                    document.getElementById('current-ip').innerText = data.configured_ip || 'Не налаштовано';
                    
                    const statusEl = document.getElementById('connection-status');
                    if (data.connected) {
                        statusEl.innerText = 'ПІДКЛЮЧЕНО (' + data.telemetry.print_state.toUpperCase() + ')';
                        statusEl.className = 'px-2 py-1 rounded text-xs font-bold bg-emerald-900 text-emerald-300';
                    } else {
                        statusEl.innerText = 'НЕМАЄ ЗВ\'ЯЗКУ (' + data.telemetry.print_state.toUpperCase() + ')';
                        statusEl.className = 'px-2 py-1 rounded text-xs font-bold bg-rose-950 text-rose-300';
                    }

                    document.getElementById('temp-extruder').innerText = data.telemetry.extruder_temp.toFixed(1) + '°C';
                    document.getElementById('target-extruder').innerText = 'Ціль: ' + data.telemetry.extruder_target.toFixed(0) + '°C';
                    document.getElementById('temp-bed').innerText = data.telemetry.bed_temp.toFixed(1) + '°C';
                    document.getElementById('target-bed').innerText = 'Ціль: ' + data.telemetry.bed_target.toFixed(0) + '°C';

                } catch (e) {
                    console.error('Помилка опитування статусу:', e);
                }
            }

            // Спосіб 1: Зберегти IP
            async function saveManualIP(ipAddress = null) {
                const ip = ipAddress || document.getElementById('manual-ip-input').value;
                if (!ip) return alert('Будь ласка, введіть коректну IP-адресу.');

                try {
                    const response = await fetch('/settings/printer-ip', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ip: ip})
                    });
                    const result = await response.json();
                    if (result.status === 'success') {
                        alert('IP-адресу ' + ip + ' успішно збережено в SQLite. Бекенд виконує підключення!');
                        document.getElementById('manual-ip-input').value = '';
                    }
                } catch (e) {
                    alert('Помилка під час збереження IP.');
                }
            }

            // Спосіб 2: Сканування мережі
            async function startScan() {
                const scanBtn = document.getElementById('scan-btn');
                const resultsDiv = document.getElementById('scan-results');
                const listDiv = document.getElementById('printers-list');

                scanBtn.innerText = '⏳ Йде сканування мережі (2 сек)...';
                scanBtn.disabled = true;

                try {
                    const response = await fetch('/settings/scan', { method: 'POST' });
                    const data = await response.json();
                    
                    listDiv.innerHTML = '';
                    resultsDiv.classList.remove('hidden');

                    if (data.status === 'success' && data.printers.length > 0) {
                        data.printers.forEach(printer => {
                            const item = document.createElement('div');
                            item.className = 'flex items-center justify-between bg-gray-900 p-2 rounded text-xs';
                            item.innerHTML = `
                                <div>
                                    <span class="font-bold text-gray-200 block">${printer.name}</span>
                                    <span class="text-gray-500 font-mono">${printer.ip}:${printer.port}</span>
                                </div>
                                <button onclick="saveManualIP('${printer.ip}')" class="bg-emerald-600 hover:bg-emerald-500 px-3 py-1 rounded text-white font-bold transition">Підключити</button>
                            `;
                            listDiv.appendChild(item);
                        });
                    } else {
                        listDiv.innerHTML = '<p class="text-xs text-gray-500 p-2">Жодного Klipper-принтера в мережі не знайдено.</p>';
                    }
                } catch (e) {
                    alert('Помилка сканування локальної мережі.');
                } finally {
                    scanBtn.innerText = '🔍 Сканувати мережу';
                    scanBtn.disabled = false;
                }
            }

            // Запускаємо опитування кожні 1.5 сек
            setInterval(pollStatus, 1500);
            pollStatus(); // Перший запуск одразу
        </script>
    </body>
    </html>
    """