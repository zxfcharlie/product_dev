import copy
import datetime
import logging
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import cast, Numeric, Date, asc, desc, or_
from pydantic import BaseModel

from ..database import get_db
from ..models import Record, SavedView, User
from ..security import get_current_user
from ..schemas_config import TABLE_SCHEMAS, get_schema, field_map, ARCHIVE_TABLE_KEYS
from .. import automation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tables", tags=["tables"])

CONFIG_TABLE_KEYS = {"task_assignee_config", "shop_config", "category_config"}


def _require_table(table_key: str):
    schema = get_schema(table_key)
    if not schema:
        raise HTTPException(404, f"未知的表: {table_key}")
    return schema


def _check_config_access(table_key: str, user: User):
    """三张配置表只有管理员能看/能改，普通成员即使直接调接口也拿不到数据。"""
    if table_key in CONFIG_TABLE_KEYS and user.role != "admin":
        raise HTTPException(403, "只有管理员可以访问配置表")


def _check_archive_writable(table_key: str):
    """历史归档表只读，不允许新增/编辑/删除，只能查询和建视图。"""
    if table_key in ARCHIVE_TABLE_KEYS:
        raise HTTPException(403, "历史归档表是只读的，不支持新增/编辑/删除")


def _safe_automation(db: Session, label: str, fn):
    """
    统一的自动化规则安全执行入口：任何自动化逻辑（联动生成任务、同步字段、归档等）
    出错时，只记录日志并回滚这一步自己产生的改动，绝不影响调用方已经保存成功的数据、
    也绝不让整个 HTTP 请求跟着失败。
    出问题时看 `docker compose logs -f web`，会看到 "[automation]" 开头的报错堆栈。
    """
    try:
        return fn()
    except Exception:
        logger.exception("[automation] %s 执行失败，已跳过，不影响本次保存", label)
        db.rollback()
        return None


def _data_expr(field_key: str, field_type: str):
    """把 Record.data[field_key] 转成合适的 SQL 表达式，用于筛选/排序。"""
    text_expr = Record.data[field_key].astext
    if field_type == "number" or field_type == "rating":
        return cast(text_expr, Numeric)
    if field_type == "date":
        return cast(text_expr, Date)
    return text_expr


def _resolve_filter_value(field_type: str, value):
    """支持筛选值填“今天”“昨天”（用于每日完成情况这类会随日期变化的视图），
    保存下来的视图第二天打开还是对的，不会固定成某个写死的日期。"""
    if field_type == "date" and isinstance(value, str):
        if value in ("今天", "今日", "__TODAY__"):
            return datetime.date.today().isoformat()
        if value in ("昨天", "昨日", "__YESTERDAY__"):
            return (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    return value


def _apply_filters(query, table_key: str, filters: list):
    fmap = field_map(table_key)
    for f in filters or []:
        key, op, raw_value = f.get("field"), f.get("op"), f.get("value")
        field = fmap.get(key)
        if not field:
            continue
        value = _resolve_filter_value(field["type"], raw_value)
        expr = _data_expr(key, field["type"])
        if op == "eq":
            query = query.filter(expr == value)
        elif op == "neq":
            query = query.filter(expr != value)
        elif op == "contains":
            query = query.filter(Record.data[key].astext.ilike(f"%{value}%"))
        elif op == "gt":
            query = query.filter(expr > value)
        elif op == "gte":
            query = query.filter(expr >= value)
        elif op == "lt":
            query = query.filter(expr < value)
        elif op == "lte":
            query = query.filter(expr <= value)
        elif op == "is_true":
            query = query.filter(Record.data[key].astext == "true")
        elif op == "is_false":
            query = query.filter(Record.data[key].astext == "false")
        elif op == "in_multiselect":
            # 多选字段里是否包含某个值（存储为 JSON 数组）
            query = query.filter(Record.data[key].astext.ilike(f"%{value}%"))
    return query


def _apply_sorts(query, table_key: str, sorts: list):
    fmap = field_map(table_key)
    for s in sorts or []:
        key, direction = s.get("field"), s.get("dir", "asc")
        field = fmap.get(key)
        if not field:
            continue
        expr = _data_expr(key, field["type"])
        query = query.order_by(asc(expr) if direction == "asc" else desc(expr))
    if not sorts:
        query = query.order_by(Record.id.asc())
    return query


def _serialize(record: Record):
    return {
        "id": record.id,
        "data": record.data,
        "creator": record.creator.display_name if record.creator else None,
        "creator_id": record.creator_id,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


@router.get("/schemas")
def list_schemas(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    schemas = copy.deepcopy(TABLE_SCHEMAS)
    active_usernames = None  # 懒加载，只有真的用到才查一次
    # 动态选项：比如 SKU 商品类目 跟 品类负责人配置表 保持同步；负责人字段跟用户管理名单保持同步
    # 这里任何一个字段的动态选项解析出错，都只跳过那一个字段（保留写死的兜底选项），
    # 不能让一条脏配置数据搞得整个系统连页面骨架都加载不出来。
    for table in schemas.values():
        for field in table["fields"]:
            src = field.get("dynamic_options")
            if not src:
                continue
            try:
                if src.get("source") == "users":
                    if active_usernames is None:
                        active_usernames = [
                            u.display_name for u in
                            db.query(User).filter(User.is_active == True).order_by(User.id.asc()).all()  # noqa: E712
                        ]
                    if active_usernames:
                        field["options"] = active_usernames
                    continue
                values = []
                seen = set()
                for r in db.query(Record).filter(Record.table_key == src["table"]).order_by(Record.id.asc()).all():
                    for fk in src["fields"]:
                        v = (r.data or {}).get(fk)
                        if v and v not in seen:
                            seen.add(v)
                            values.append(v)
                if values:
                    field["options"] = values
            except Exception:
                logger.exception("解析字段 %s 的动态选项失败，使用写死的兜底选项", field.get("key"))
    # 配置表只对管理员可见（连表结构定义都不返回给普通成员，前端自然不会显示对应菜单）
    if user.role != "admin":
        schemas = {k: v for k, v in schemas.items() if v.get("group") != "config"}
    return schemas


class QueryIn(BaseModel):
    filters: Optional[list] = []
    sorts: Optional[list] = []


@router.post("/{table_key}/query")
def query_records(table_key: str, payload: QueryIn, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    _require_table(table_key)
    _check_config_access(table_key, user)
    try:
        query = db.query(Record).filter(Record.table_key == table_key)
        query = _apply_filters(query, table_key, payload.filters)
        query = _apply_sorts(query, table_key, payload.sorts)
        records = query.all()
    except Exception:
        # 筛选/排序条件跟脏数据撞在一起可能导致类型转换报错，这里保底：
        # 让用户至少还能看到这张表的数据（不排序不筛选），不至于连表都打不开。
        logger.exception("查询 %s 时筛选/排序失败，已回退为不筛选不排序的默认列表", table_key)
        db.rollback()
        records = db.query(Record).filter(Record.table_key == table_key).order_by(Record.id.asc()).all()
    return [_serialize(r) for r in records]


class RecordIn(BaseModel):
    data: dict[str, Any]


@router.post("/{table_key}/records")
def create_record(table_key: str, payload: RecordIn, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    schema = _require_table(table_key)
    _check_config_access(table_key, user)
    _check_archive_writable(table_key)
    fmap = field_map(table_key)
    clean_data = {}
    for key, field in fmap.items():
        if field.get("auto"):
            continue
        if key in payload.data:
            clean_data[key] = payload.data[key]
    for field in schema["fields"]:
        if field["type"] == "date" and field.get("auto"):
            clean_data[field["key"]] = datetime.date.today().isoformat()
        if field["type"] == "user" and field.get("auto"):
            clean_data[field["key"]] = user.display_name

    # 二期自动化：SKU 编号自动生成 gzs-yymmdd-00001（失败则退化成时间戳编号，保证仍能建SKU）
    if table_key == "sku":
        clean_data["sku_code"] = (
            _safe_automation(db, "generate_sku_code", lambda: automation.generate_sku_code(db))
            or f"gzs-{datetime.datetime.utcnow().strftime('%y%m%d%H%M%S')}"
        )

    # 二期自动化：新建任务时按配置表自动分配负责人，覆盖表单里可能带的值
    if table_key in ("ai_creative", "set_task"):
        assigned = _safe_automation(
            db, "assign_maker_for_create",
            lambda: automation.assign_maker_for_create(db, table_key, clean_data.get("related_sku")),
        )
        if assigned:
            clean_data["maker"] = assigned
    elif table_key == "pending_listing":
        shop_fields = _safe_automation(
            db, "assign_shop_fields_for_create",
            lambda: automation.assign_shop_fields_for_create(db, clean_data.get("related_sku")),
        )
        if shop_fields:
            if shop_fields.get("shop_name"):
                clean_data["shop_name"] = shop_fields["shop_name"]
            if shop_fields.get("shop_owner"):
                clean_data["shop_owner"] = shop_fields["shop_owner"]

    # 主记录先独立提交：不管后面的自动化联动是否出问题，这条记录本身一定能保存成功
    record = Record(table_key=table_key, data=clean_data, creator_id=user.id)
    db.add(record)
    db.commit()
    db.refresh(record)

    # 二期自动化：SKU 创建后自动生成 AI 主图二创任务（单独一个事务，出错不影响上面已保存的SKU）
    if table_key == "sku":
        _safe_automation(db, "on_sku_created", lambda: (
            automation.on_sku_created(db, record, user.id), db.commit()
        ))
        db.refresh(record)

    return _serialize(record)


@router.put("/{table_key}/records/{record_id}")
def update_record(table_key: str, record_id: int, payload: RecordIn, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    _require_table(table_key)
    _check_config_access(table_key, user)
    _check_archive_writable(table_key)
    record = db.query(Record).filter(Record.id == record_id, Record.table_key == table_key).first()
    if not record:
        raise HTTPException(404, "记录不存在")
    fmap = field_map(table_key)
    previous_data = dict(record.data or {})
    new_data = dict(record.data or {})
    for key, value in payload.data.items():
        field = fmap.get(key)
        if field and not field.get("auto"):
            new_data[key] = value
    record.data = new_data

    # 主字段修改先独立提交：这一步成功了，用户点保存这个动作就不会失败，
    # 不管下面的联动自动化是否出问题
    db.commit()
    db.refresh(record)

    # 三期自动化：状态变化时同步 SKU 开发阶段 / 记录完成时间 / 自动生成下游任务
    # 拆成多个独立的自动化步骤，各自单独提交——就算“生成下游任务”这步出问题，
    # 前面已经成功记录的“完成时间”“开发阶段同步”不会被连累撤销。
    if table_key == "ai_creative":
        _safe_automation(db, "on_ai_creative_saved", lambda: (
            automation.on_ai_creative_saved(db, record, previous_data.get("status"), user.id), db.commit()
        ))
        db.refresh(record)
        _safe_automation(db, "spawn_set_task_if_needed", lambda: (
            automation.spawn_set_task_if_needed(db, record, user.id), db.commit()
        ))
    elif table_key == "set_task":
        _safe_automation(db, "on_set_task_saved", lambda: (
            automation.on_set_task_saved(db, record, previous_data.get("status"), user.id), db.commit()
        ))
        db.refresh(record)
        _safe_automation(db, "spawn_pending_listing_if_needed", lambda: (
            automation.spawn_pending_listing_if_needed(db, record, user.id), db.commit()
        ))
    elif table_key == "pending_listing":
        _safe_automation(db, "on_pending_listing_saved", lambda: (
            automation.on_pending_listing_saved(db, record, previous_data.get("is_listed")), db.commit()
        ))
        if new_data.get("is_listed") in (True, "true"):
            _safe_automation(db, "run_archive_if_needed", lambda: (
                automation.run_archive_if_needed(db), db.commit()
            ))
    elif table_key == "sku" and new_data.get("priority") != previous_data.get("priority"):
        _safe_automation(db, "sync_priority_to_tasks", lambda: (
            automation.sync_priority_to_tasks(db, new_data.get("sku_code"), new_data.get("priority")), db.commit()
        ))

    db.refresh(record)
    return _serialize(record)


@router.delete("/{table_key}/records/{record_id}")
def delete_record(table_key: str, record_id: int, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    _require_table(table_key)
    _check_config_access(table_key, user)
    _check_archive_writable(table_key)
    record = db.query(Record).filter(Record.id == record_id, Record.table_key == table_key).first()
    if not record:
        raise HTTPException(404, "记录不存在")
    if user.role != "admin" and record.creator_id != user.id:
        raise HTTPException(403, "只能删除自己创建的记录")
    db.delete(record)
    db.commit()
    return {"ok": True}


# ---------------- 视图（Views） ----------------

class ViewIn(BaseModel):
    name: str
    filters: Optional[list] = []
    sorts: Optional[list] = []
    is_shared: bool = True


@router.get("/{table_key}/views")
def list_views(table_key: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_table(table_key)
    _check_config_access(table_key, user)
    views = db.query(SavedView).filter(
        SavedView.table_key == table_key
    ).filter(or_(SavedView.is_shared == True, SavedView.owner_id == user.id)).all()  # noqa: E712
    return [
        {"id": v.id, "name": v.name, "filters": v.filters, "sorts": v.sorts,
         "is_shared": v.is_shared, "owner_id": v.owner_id}
        for v in views
    ]


@router.post("/{table_key}/views")
def create_view(table_key: str, payload: ViewIn, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    _require_table(table_key)
    _check_config_access(table_key, user)
    view = SavedView(
        table_key=table_key, name=payload.name, owner_id=user.id,
        filters=payload.filters, sorts=payload.sorts, is_shared=payload.is_shared,
    )
    db.add(view)
    db.commit()
    db.refresh(view)
    return {"id": view.id, "name": view.name}


@router.delete("/{table_key}/views/{view_id}")
def delete_view(table_key: str, view_id: int, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    _check_config_access(table_key, user)
    view = db.query(SavedView).filter(SavedView.id == view_id, SavedView.table_key == table_key).first()
    if not view:
        raise HTTPException(404, "视图不存在")
    if user.role != "admin" and view.owner_id != user.id:
        raise HTTPException(403, "只能删除自己创建的视图")
    db.delete(view)
    db.commit()
    return {"ok": True}
