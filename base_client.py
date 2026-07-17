import abc

class BasePrinterClient(abc.ABC):
    def __init__(self, host: str = "", port: int = 7125):
        self.host = host
        self.port = port
        self.active_ws = None
        self.is_connected = False
        
        # Наш єдиний уніфікований стандарт стану принтера.
        # Будь-який принтер (Klipper, Marlin чи Bambu) зобов'язаний записувати дані саме сюди.
        self.state = {
            "connected": False,
            "print_state": "disconnected",
            "temps": {
                "extruder": {"current": 0.0, "target": 0.0},
                "bed": {"current": 0.0, "target": 0.0},
                "chamber": {"current": 0.0, "target": 0.0}
            },
            "fans": {
                "part_cooling": 0.0  # від 0 до 100%
            },
            "raw_telemetry": {}  # Сюди зливатимемо всі інші "сирі" дані для дебаг-монітора
        }

    @abc.abstractmethod
    def set_host(self, host: str):
        """Встановлення адреси пристрою"""
        pass

    @abc.abstractmethod
    async def update_host_and_reconnect(self, new_host: str):
        """Оновлення адреси та перезапуск з'єднання"""
        pass

    @abc.abstractmethod
    async def send_gcode(self, gcode: str) -> dict:
        """Відправка команди G-коду"""
        pass

    @abc.abstractmethod
    async def start_websocket_listener(self):
        """Запуск фонового слухача телеметрії"""
        pass