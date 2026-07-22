import os
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from core.database import BASE_DIR

router = APIRouter(tags=["Frontend"])

@router.get("/", response_class=HTMLResponse)
def get_home_page():
    html_path = os.path.join(BASE_DIR, "templates", "index.html")
    try:
        with open(html_path, "r", encoding="utf-8") as f: 
            return f.read()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Файл шаблону templates/index.html не знайдено.")