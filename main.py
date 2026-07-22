from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from printer_manager import PrinterManager
from core.database import init_db
from routers import auth, printers, inventory, frontend

# 1. Ініціалізуємо базу даних при старті
init_db()

# 2. Створюємо глобальний менеджер принтерів
manager = PrinterManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Додаємо менеджер у стан додатку, щоб роутери могли до нього звертатися (request.app.state.manager)
    app.state.manager = manager
    # Запускаємо всі принтери з БД у фоновому режимі
    manager.load_all_printers()
    
    yield # Тут сервер працює і приймає запити
    
    # Коли сервер вимикається, коректно зупиняємо всі фонові процеси
    await manager.shutdown()

# 3. Створюємо екземпляр FastAPI
app = FastAPI(title="Secure Printer Gateway", lifespan=lifespan)

# 4. Налаштовуємо CORS (дозволяємо запити з будь-яких джерел)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 5. Підключаємо наші розділені модулі (ендпоінти)
app.include_router(frontend.router)
app.include_router(auth.router)
app.include_router(printers.router)
app.include_router(inventory.router)