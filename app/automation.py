"""
二期自动化规则引擎。

覆盖的规则：
1. SKU 创建 -> 自动生成一条 AI主图二创任务（制作人按 task_assignee_config 轮询分配），
   SKU.开发阶段 自动置为「AI主图制作中」。
2. AI主图任务状态变化 -> 实时同步 SKU.开发阶段；变为「已完成」时自动生成套图任务（幂等，
   同一条 AI 任务只会触发一次）。
3. 套图任务状态变化 -> 实时同步 SKU.开发阶段；变为「已完成」时自动生成上架任务
   （店铺负责人优先按 SKU 品类匹配 category_config，匹配不到则走任务负责人配置表轮询兜底）。
4. 上架任务「是否已上架」变化 -> 实时同步 SKU.开发阶段（已上架 / 待上架）。

设计上所有自动创建的任务的 “制作人/店铺负责人” 字段都由这里的轮询逻辑决定，
用户手动新建业务表记录时也会经过这里分配（对应需求里“任务创建的时候默认按顺序分配”）。
"""
import datetime
from typing import Optional
from sqlalchemy.orm import Session

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


def _find_config_by(db: Session, table_key: str, field: str, value: str) -> Optional[Record]:
    for r in _all_records(db, table_key):
        if (r.data or {}).get(field) == value:
            return r
    return None


def assign_round_robin(db: Session, task_type_key: str) -> Optional[str]:
    """从任务负责人配置表按顺序取下一个负责人，并推进轮询指针。没配置则返回 None。"""
    label = TASK_TYPE_LABELS.get(task_type_key)
    if not label:
        return None
    config = _find_config_by(db, "task_assignee_config", "task_type", label)
    if not config:
        return None
    data = dict(config.data or {})
    assignees = [a.strip() for a in (data.get("assignees") or "").split(",") if a.strip()]
    if not assignees:
        return None
    try:
        idx = int(data.get("next_assign_index") or 0)
    except (TypeError, ValueError):
        idx = 0
    idx = idx % len(assignees)
    chosen = assignees[idx]
    data["next_assign_index"] = (idx + 1) % len(assignees)
    config.data = data
    db.add(config)
    return chosen


def resolve_shop_owner_by_category(db: Session, sku_categories) -> Optional[str]:
    """按 SKU 品类去品类负责人配置表匹配负责人（一级或二级类目命中即可）。"""
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
    db.add(sku_record)


def assign_maker_for_create(db: Session, table_key: str) -> Optional[str]:
    """新建 ai_creative / set_task 记录（无论手动还是自动）时，用来决定“制作人”字段。"""
    return assign_round_robin(db, table_key)


def assign_shop_owner_for_create(db: Session, related_sku: Optional[str]) -> Optional[str]:
    """新建 pending_listing 记录时，用来决定“店铺负责人”字段：先按品类匹配，匹配不到再轮询兜底。"""
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
