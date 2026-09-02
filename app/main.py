import json
import time
from fastapi import FastAPI, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError
from sqlalchemy import text

from .database import Base, engine, get_db
from .routers import auth as auth_router
from .routers import tables as tables_router
from .routers import admin as admin_router
from .routers import dashboard as dashboard_router
from .security import get_current_user_optional

app = FastAPI(title="Etsy 运营任务管理系统")


def _init_db_with_retry(max_attempts=10, delay_seconds=2):
    """容器启动时数据库可能还没就绪，重试几次再建表，避免因为一次性连接失败就整个崩溃。"""
    for attempt in range(1, max_attempts + 1):
        try:
            Base.metadata.create_all(bind=engine)
            _run_lightweight_migrations()
            return
        except OperationalError:
            if attempt == max_attempts:
                raise
            time.sleep(delay_seconds)


def _run_lightweight_migrations():
    """
    项目没有引入 Alembic 这类迁移框架，字段全部用轻量的 ADD COLUMN IF NOT EXISTS
    补齐——这样老部署直接重启容器就能拿到新字段，不需要手动跑迁移脚本。
    """
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS note TEXT"))


_init_db_with_retry()

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

app.include_router(auth_router.router)
app.include_router(tables_router.router)
app.include_router(admin_router.router)
app.include_router(dashboard_router.router)


@app.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/register")
def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})


@app.get("/")
def index(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_optional(request, db)
    if not user:
        return RedirectResponse("/login")
    user_json = json.dumps({
        "id": user.id, "display_name": user.display_name, "role": user.role,
    })
    return templates.TemplateResponse(
        "index.html", {"request": request, "user": user, "user_json": user_json}
    )


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
