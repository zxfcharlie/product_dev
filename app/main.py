import json
import logging
import time
from fastapi import FastAPI, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError
from sqlalchemy import text

from .database import Base, engine, get_db
from .models import Record, SavedView, User as UserModel
from .routers import auth as auth_router
from .routers import tables as tables_router
from .routers import admin as admin_router
from .routers import dashboard as dashboard_router
from .security import get_current_user_optional

logger = logging.getLogger(__name__)

app = FastAPI(title="Etsy 运营任务管理系统")


def _init_db_with_retry(max_attempts=10, delay_seconds=2):
    """容器启动时数据库可能还没就绪，重试几次再建表，避免因为一次性连接失败就整个崩溃。"""
    for attempt in range(1, max_attempts + 1):
        try:
            Base.metadata.create_all(bind=engine)
            break
        except OperationalError:
            if attempt == max_attempts:
                raise
            time.sleep(delay_seconds)

    # 建表是应用能启动的硬前提，下面这些都是维护性的“锦上添花”步骤——
    # 任何一步出错都只记日志、绝不能阻止整个应用启动（不然一个小迁移脚本的bug
    # 就会导致容器不断重启崩溃，之前的问题很可能就出在这类地方）。
    _safe_startup_step("run_lightweight_migrations", _run_lightweight_migrations)
    _safe_startup_step("migrate_market_heat_to_priority", _migrate_market_heat_to_priority)
    _safe_startup_step("seed_default_views", _seed_default_views)


def _safe_startup_step(label, fn):
    try:
        fn()
    except Exception:
        logger.exception("[startup] %s 执行失败，已跳过，不影响应用启动", label)


def _run_lightweight_migrations():
    """
    项目没有引入 Alembic 这类迁移框架，字段全部用轻量的 ADD COLUMN IF NOT EXISTS
    补齐——这样老部署直接重启容器就能拿到新字段，不需要手动跑迁移脚本。
    """
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS note TEXT"))


def _migrate_market_heat_to_priority():
    """SKU 的“市场热度”字段改名叫“优先级”，key 也从 market_heat 换成 priority，
    这里把老数据里已经存在的 market_heat 值原样搬到 priority，不丢数据。"""
    session = Session(bind=engine)
    try:
        records = session.query(Record).filter(Record.table_key == "sku").all()
        changed = False
        for r in records:
            d = r.data or {}
            if "market_heat" in d and "priority" not in d:
                new_d = dict(d)
                new_d["priority"] = new_d.pop("market_heat")
                r.data = new_d
                changed = True
        if changed:
            session.commit()
    finally:
        session.close()


def _seed_default_views():
    """给 AI主图/套图/待上架 三张任务表各建一个团队共享视图：筛选“今天完成”的任务，
    方便每天一打开就能看当天进度。如果还没有管理员账号（全新部署），先跳过，
    等第一个管理员注册之后，下次重启会自动补上。"""
    session = Session(bind=engine)
    try:
        admin = session.query(UserModel).filter(UserModel.role == "admin").order_by(UserModel.id.asc()).first()
        if not admin:
            return
        for table_key in ("ai_creative", "set_task", "pending_listing"):
            exists = session.query(SavedView).filter(
                SavedView.table_key == table_key,
                SavedView.name == "今日完成",
                SavedView.is_shared == True,  # noqa: E712
            ).first()
            if exists:
                continue
            view = SavedView(
                table_key=table_key, name="今日完成", owner_id=admin.id,
                filters=[{"field": "finished_at", "op": "eq", "value": "今天"}],
                sorts=[], is_shared=True,
            )
            session.add(view)
        session.commit()
    finally:
        session.close()


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
