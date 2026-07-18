# Використовуємо легкий офіційний образ Python
FROM python:3.12-slim

# Встановлюємо робочу директорію всередині контейнера
WORKDIR /app

# Встановлюємо системні утиліти, необхідні для компіляції деяких пакетів
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Копіюємо список залежностей
COPY requirements.txt .

# Встановлюємо бібліотеки Python
RUN pip install --no-cache-dir -r requirements.txt

# Копіюємо весь інший код проєкту
COPY . .

# Створюємо папку для збереження бази даних
RUN mkdir -p /app/data

# Відкриваємо порт
EXPOSE 8000

# Команда для запуску нашого FastAPI сервера
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]