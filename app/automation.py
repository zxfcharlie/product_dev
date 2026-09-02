"""二期自动化规则引擎。"""
import datetime
import re
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from .models import Record

TASK_TYPE_LABELS = {
    "ai_creative": "AI主图任务",
    "set_task": "套图任务",
    "pending_listing": "上架任务",
}


def _all_records(db: Session, table_key: str):
    return db.query(Record).filter(Record.table_key == table_key).all()


def find_sku_by_code(db: Session, sku_code: Optional[str]) -> Optional[Record]:
    if not sku_code:
        return None
    for r in _all_records(db, "sku"):
        if (r.data or {}).get("sku_code") == sku_code:
            return r
    return None


def generate_sku_code(db: Session) -> str:
    """SKU: gzs-yymmdd00001；序号每天从 00001 开始并递增。"""
    prefix = f"gzs-{datetime.date.today().strftime('%y%m%d')}"
    max_seq = 0
    for r in _all_records(db, "sku"):
        code = str((r.data or {}).get("sku_code") or "")
        if code.startswith(prefix):
            m = re.fullmatch(re.escape(prefix) + r"(\d{5})", code)
            if m:
                max_seq = max(max_seq, int(m.group(1)))
    return f"{prefix}{max_seq + 1:05d}"


def generate_task_code(db: Session, table_key: str) -> str:
    seq = db.query(Record).filter(Record.table_key == table_key).count() + 1
    today = datetime.date.today().strftime("%Y%m%d")
    if table_key == "ai_creative":
        return f"AI-{seq:04d}{today}"
    if table_key == "set_task":
        return f"SET-{seq:04d}"
    if table_key == "pending_listing":
        return f"PENDING-{seq:04d}"
    return f"{table_key.upper()}-{seq:04d}"


def assign_round_robin(db: Session, task_type_key: str) -> Optional[str]:
    """按负责人配置顺序轮询，并使用行锁保证多人同时创建任务时也能正确推进。"""
    label = TASK_TYPE_LABELS.get(task_type_key)
    if not label:
        return None

    # PostgreSQL JSONB 字段条件 + FOR UPDATE，锁定这一条负责人配置。
    config = (
        db.query(Record)
        .filter(Record.table_key == "task_assignee_config")
        .filter(Record.data["task_type"].astext == label)
        .with_for_update()
        .first()
    )
    if not config:
        return None

    data = dict(config.data or {})
    raw = str(data.get("assignees") or "")
    # 兼容英文逗号、中文逗号、分号和换行。
    assignees = [a.strip() for a in re.split(r"[,，;；\n]+", raw) if a.strip()]
    if not assignees:
        return None

    try:
        idx = int(data.get("next_assign_index") or 0)
    except (TypeError, ValueError):
        idx = 0
    idx %= len(assignees)
    chosen = assignees[idx]
    data["next_assign_index"] = (idx + 1) % len(assignees)
    config.data = data
    flag_modified(config, "data")
    db.add(config)
    db.flush()
    return chosen


def resolve_shop_owner_by_category(db: Session, sku_categories) -> Optional[str]:
    if not sku_categories:
        return None
    if isinstance(sku_categories, str):
        sku_categories = [sku_categories]
    configs = _all_records(db, "category_config")
    for cat in sku_categories:
        cat = (cat or "").strip()
        if not cat:
            continue
        for c in configs:
            d = c.data or {}
            if cat == (d.get("level1_category") or "").strip() or cat == (d.get("level2_category") or "").strip():
                person = (d.get("responsible_person") or "").strip()
                if person:
                    return person
    return None


def _create_record(db: Session, table_key: str, data: dict, creator_id: int) -> Record:
    record = Record(table_key=table_key, data=data, creator_id=creator_id)
    db.add(record)
    db.flush()
    return record


def sync_sku_dev_stage(db: Session, sku_code: Optional[str], dev_stage: str) -> None:
    sku_record = find_sku_by_code(db, sku_code)
    if not sku_record:
        return
    data = dict(sku_record.data or {})
    if data.get("dev_stage") == dev_stage:
        return
    data["dev_stage"] = dev_stage
    sku_record.data = data
    flag_modified(sku_record, "data")
    db.add(sku_record)


def assign_maker_for_create(db: Session, table_key: str) -> Optional[str]:
    return assign_round_robin(db, table_key)


def assign_shop_owner_for_create(db: Session, related_sku: Optional[str]) -> Optional[str]:
    sku_record = find_sku_by_code(db, related_sku)
    sku_categories = (sku_record.data or {}).get("category") if sku_record else None
    owner = resolve_shop_owner_by_category(db, sku_categories)
    if owner:
        return owner
    return assign_round_robin(db, "pending_listing")


def on_sku_created(db: Session, sku_record: Record, creator_id: int) -> None:
    data = dict(sku_record.data or {})
    sku_code = data.get("sku_code")
    data["dev_stage"] = "AI主图制作中"
    sku_record.data = data
    flag_modified(sku_record, "data")
    db.add(sku_record)

    ai_data = {
        "task_code": generate_task_code(db, "ai_creative"),
        "related_sku": sku_code,
        "status": "待制作",
        "maker": assign_maker_for_create(db, "ai_creative") or "",
        "competitor_link": data.get("competitor_link", ""),
        "design_highlight": data.get("design_highlight", ""),
        "created_at": datetime.date.today().isoformat(),
    }
    _create_record(db, "ai_creative", ai_data, creator_id)


def on_ai_creative_saved(db: Session, record: Record, previous_status: Optional[str], creator_id: int) -> None:
    data = record.data or {}
    status = data.get("status")
    sku_code = data.get("related_sku")
    if status == previous_status:
        return
    if status in ("待制作", "制作中"):
        sync_sku_dev_stage(db, sku_code, "AI主图制作中")
    elif status == "已完成":
        sync_sku_dev_stage(db, sku_code, "套图制作中")
        if not data.get("_spawned_set_task"):
            set_data = {
                "task_code": generate_task_code(db, "set_task"),
                "related_sku": sku_code,
                "status": "待制作",
                "maker": assign_maker_for_create(db, "set_task") or "",
                "competitor_link": data.get("competitor_link", ""),
                "created_at": datetime.date.today().isoformat(),
            }
            _create_record(db, "set_task", set_data, creator_id)
            new_data = dict(data)
            new_data["_spawned_set_task"] = True
            record.data = new_data
            flag_modified(record, "data")
            db.add(record)


def on_set_task_saved(db: Session, record: Record, previous_status: Optional[str], creator_id: int) -> None:
    data = record.data or {}
    status = data.get("status")
    sku_code = data.get("related_sku")
    if status == previous_status:
        return
    if status in ("待制作", "制作中"):
        sync_sku_dev_stage(db, sku_code, "套图制作中")
    elif status == "已完成":
        sync_sku_dev_stage(db, sku_code, "待上架")
        if not data.get("_spawned_pending"):
            pending_data = {
                "task_code": generate_task_code(db, "pending_listing"),
                "note": f"套图任务完成自动创建 - SKU: {sku_code}",
                "is_listed": False,
                "shop_owner": assign_shop_owner_for_create(db, sku_code) or "",
                "related_sku": sku_code,
                "created_at": datetime.date.today().isoformat(),
            }
            _create_record(db, "pending_listing", pending_data, creator_id)
            new_data = dict(data)
            new_data["_spawned_pending"] = True
            record.data = new_data
            flag_modified(record, "data")
            db.add(record)


def on_pending_listing_saved(db: Session, record: Record, previous_is_listed) -> None:
    data = record.data or {}
    is_listed = data.get("is_listed")
    sku_code = data.get("related_sku")
    if is_listed == previous_is_listed or not sku_code:
        return
    if is_listed in (True, "true"):
        sync_sku_dev_stage(db, sku_code, "已上架")
    else:
        sync_sku_dev_stage(db, sku_code, "待上架")
