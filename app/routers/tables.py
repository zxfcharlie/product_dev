import datetime
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import cast, Numeric, Date, asc, desc, or_
from pydantic import BaseModel

from ..database import get_db
from ..models import Record, SavedView, User
from ..security import get_current_user
from ..schemas_config import TABLE_SCHEMAS, get_schema, field_map

router = APIRouter(prefix="/api/tables", tags=["tables"])


def _require_table(table_key: str):
    schema = get_schema(table_key)
    if not schema:
        raise HTTPException(404, f"未知的表: {table_key}")
    return schema


def _data_expr(field_key: str, field_type: str):
    """把 Record.data[field_key] 转成合适的 SQL 表达式，用于筛选/排序。"""
    text_expr = Record.data[field_key].astext
    if field_type == "number" or field_type == "rating":
        return cast(text_expr, Numeric)
    if field_type == "date":
        return cast(text_expr, Date)
    return text_expr


def _apply_filters(query, table_key: str, filters: list):
    fmap = field_map(table_key)
    for f in filters or []:
        key, op, value = f.get("field"), f.get("op"), f.get("value")
        field = fmap.get(key)
        if not field:
            continue
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
def list_schemas(user: User = Depends(get_current_user)):
    return TABLE_SCHEMAS


class QueryIn(BaseModel):
    filters: Optional[list] = []
    sorts: Optional[list] = []


@router.post("/{table_key}/query")
def query_records(table_key: str, payload: QueryIn, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    _require_table(table_key)
    query = db.query(Record).filter(Record.table_key == table_key)
    query = _apply_filters(query, table_key, payload.filters)
    query = _apply_sorts(query, table_key, payload.sorts)
    records = query.all()
    return [_serialize(r) for r in records]


class RecordIn(BaseModel):
    data: dict[str, Any]


@router.post("/{table_key}/records")
def create_record(table_key: str, payload: RecordIn, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    schema = _require_table(table_key)
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
    record = Record(table_key=table_key, data=clean_data, creator_id=user.id)
    db.add(record)
    db.commit()
    db.refresh(record)
    return _serialize(record)


@router.put("/{table_key}/records/{record_id}")
def update_record(table_key: str, record_id: int, payload: RecordIn, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    _require_table(table_key)
    record = db.query(Record).filter(Record.id == record_id, Record.table_key == table_key).first()
    if not record:
        raise HTTPException(404, "记录不存在")
    fmap = field_map(table_key)
    new_data = dict(record.data or {})
    for key, value in payload.data.items():
        field = fmap.get(key)
        if field and not field.get("auto"):
            new_data[key] = value
    record.data = new_data
    db.commit()
    db.refresh(record)
    return _serialize(record)


@router.delete("/{table_key}/records/{record_id}")
def delete_record(table_key: str, record_id: int, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    _require_table(table_key)
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
    view = db.query(SavedView).filter(SavedView.id == view_id, SavedView.table_key == table_key).first()
    if not view:
        raise HTTPException(404, "视图不存在")
    if user.role != "admin" and view.owner_id != user.id:
        raise HTTPException(403, "只能删除自己创建的视图")
    db.delete(view)
    db.commit()
    return {"ok": True}
