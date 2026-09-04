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
5. SKU「优先级」变化 -> 实时同步到它关联的 AI主图任务 / 套图任务 的「优先级」字段；
   自动创建 AI主图任务 / 套图任务 时也会带上 SKU 当前的优先级。
6. 已上架 SKU 达到 200 个时 -> 自动把最早上架的一批 SKU（及其关联的所有任务表记录）
   归档到历史表，只在工作表里保留最近一批。

设计上所有自动创建的任务的 “制作人/店铺负责人” 字段都由这里的轮询逻辑决定，
用户手动新建业务表记录时也会经过这里分配（对应需求里“任务创建的时候默认按顺序分配”）。

这个文件里的函数都是被 routers/tables.py 用 `_safe_automation` 包了一层再调用的：
任何一步自动化失败，只会被记日志、回滚自己产生的改动，不会导致调用方那次保存请求失败。
"""
import datetime
import logging
import re
from typing import Optional
from sqlalchemy.orm import Session

from .models import Record

logger = logging.getLogger(__name__)

TASK_TYPE_LABELS = {
    "ai_creative": "AI主图任务",
    "set_task": "套图任务",
    "pending_listing": "上架任务",
}

_SPLIT_RE = re.compile(r"[,，、;；\n]+")  # 兼容英文逗号/中文逗号/顿号/分号/换行，容错用户手误


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
    """gzs-yymmdd-00001，按天重置流水号。"""
    today = datetime.date.today()
    prefix = f"gzs-{today.strftime('%y%m%d')}-"
    count = 0
    for r in _all_records(db, "sku"):
        code = (r.data or {}).get("sku_code") or ""
        if code.startswith(prefix):
            count += 1
    return f"{prefix}{count + 1:05d}"


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


def assign_round_robin(db: Session, task_type_key: str, sku_categories=None) -> Optional[str]:
    """
    按任务类型（可选：再按品类）做轮询分配。

    容错设计：管理员既可能在“任务负责人配置表”里新建一行、把多个人用逗号写在
    一个“负责人”字段里，也可能习惯一人一行、建多条同类型的配置记录。
    这里统一把同一 task_type 下所有配置行的负责人合并成一个有序名单再轮询，
    轮询指针存在这批配置里 id 最小的那一行上，两种填法都能正确轮流分配。

    每一行配置可以选填“适用品类”：不填表示适用所有品类（老数据没有这个字段，
    同样按“适用所有品类”处理，完全向后兼容）；填了的话，只有这行的品类跟传入的
    sku_categories 有交集时，这行的负责人才会参与本次轮询。
    """
    label = TASK_TYPE_LABELS.get(task_type_key)
    if not label:
        return None
    all_configs = [
        r for r in _all_records(db, "task_assignee_config")
        if (r.data or {}).get("task_type") == label
    ]
    if not all_configs:
        return None

    categories = _normalize_category_list(sku_categories)

    def config_applies(c) -> bool:
        cfg_categories = _normalize_category_list((c.data or {}).get("categories"))
        if not cfg_categories:
            return True  # 没限定品类 = 适用所有品类
        return any(cat in cfg_categories for cat in categories)

    configs = [c for c in all_configs if config_applies(c)]
    if not configs:
        return None
    configs.sort(key=lambda r: r.id)

    assignees = []
    for c in configs:
        raw = (c.data or {}).get("assignees")
        if isinstance(raw, list):
            names = [str(a).strip() for a in raw if str(a).strip()]
        else:
            names = [a.strip() for a in _SPLIT_RE.split(raw or "") if a.strip()]
        assignees.extend(names)
    if not assignees:
        return None

    pointer_holder = configs[0]
    data = dict(pointer_holder.data or {})
    try:
        idx = int(data.get("next_assign_index") or 0)
    except (TypeError, ValueError):
        idx = 0
    idx = idx % len(assignees)
    chosen = assignees[idx]
    data["next_assign_index"] = (idx + 1) % len(assignees)
    pointer_holder.data = data
    db.add(pointer_holder)
    return chosen


def _normalize_category_list(value) -> list:
    if not value:
        return []
    if isinstance(value, str):
        value = [value]
    return [str(c).strip() for c in value if c and str(c).strip()]


def resolve_shop_for_category(db: Session, sku_categories):
    """
    按 SKU 品类找归属的店铺和负责人，返回 (店铺名, 负责人) 二元组，两者都可能是 None。

    优先级：
    1. 店铺配置表——按“所属品类”命中的店铺，负责人就是这个店铺的负责人（也带出店铺名）。
    2. 品类负责人配置表——命中了但没配对应店铺时的兜底，只有负责人、没有店铺名。
    3. 都没匹配到，交给调用方再走任务负责人配置表轮询兜底。
    """
    categories = _normalize_category_list(sku_categories)
    if not categories:
        return None, None

    for shop in _all_records(db, "shop_config"):
        d = shop.data or {}
        shop_categories = _normalize_category_list(d.get("category"))
        if any(c in shop_categories for c in categories):
            shop_name = (d.get("shop_name") or "").strip() or None
            owner = (d.get("responsible_person") or "").strip() or None
            if shop_name or owner:
                return shop_name, owner

    for cfg in _all_records(db, "category_config"):
        d = cfg.data or {}
        level1 = (d.get("level1_category") or "").strip()
        level2 = (d.get("level2_category") or "").strip()
        if any(c == level1 or c == level2 for c in categories):
            person = (d.get("responsible_person") or "").strip()
            if person:
                return None, person

    return None, None


def assign_shop_fields_for_create(db: Session, related_sku: Optional[str]) -> dict:
    """新建上架任务时，决定“所属店铺”和“店铺负责人”两个字段。"""
    sku_record = find_sku_by_code(db, related_sku)
    sku_categories = (sku_record.data or {}).get("category") if sku_record else None
    shop_name, owner = resolve_shop_for_category(db, sku_categories)
    if not owner:
        owner = assign_round_robin(db, "pending_listing", sku_categories)
    return {"shop_name": shop_name or "", "shop_owner": owner or ""}


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


def sync_priority_to_tasks(db: Session, sku_code: Optional[str], priority) -> None:
    """SKU 的“优先级”改变时，同步到它关联的 AI主图任务 / 套图任务 的“优先级”字段。"""
    if not sku_code:
        return
    for table_key in ("ai_creative", "set_task"):
        for r in _all_records(db, table_key):
            if (r.data or {}).get("related_sku") != sku_code:
                continue
            d = dict(r.data or {})
            if d.get("priority") == priority:
                continue
            d["priority"] = priority
            r.data = d
            db.add(r)


def assign_maker_for_create(db: Session, table_key: str, related_sku: Optional[str] = None) -> Optional[str]:
    """新建 ai_creative / set_task 记录（无论手动还是自动）时，用来决定“制作人”字段。
    传入 related_sku 时会按 SKU 的品类过滤任务负责人配置表里限定了品类的配置行。"""
    sku_record = find_sku_by_code(db, related_sku) if related_sku else None
    sku_categories = (sku_record.data or {}).get("category") if sku_record else None
    return assign_round_robin(db, table_key, sku_categories)


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
        "maker": assign_round_robin(db, "ai_creative", data.get("category")) or "",
        "competitor_link": data.get("competitor_link", ""),
        "design_highlight": data.get("design_highlight", ""),
        "priority": data.get("priority", 0),
        "created_at": datetime.date.today().isoformat(),
    }
    _create_record(db, "ai_creative", ai_data, creator_id)


def on_ai_creative_saved(db: Session, record: Record, previous_status: Optional[str], creator_id: int) -> None:
    """
    状态变化时先做“基本不会出错”的部分：同步 SKU 开发阶段、标记完成时间。
    生成下游套图任务放在 spawn_set_task_if_needed 里单独一个自动化步骤——
    就算生成下游任务那步出问题，这里已经记录的完成时间也不会被连累撤销。
    """
    data = record.data or {}
    status = data.get("status")
    sku_code = data.get("related_sku")
    if status == previous_status:
        return
    if status in ("待制作", "制作中"):
        sync_sku_dev_stage(db, sku_code, "AI主图制作中")
        return
    if status != "已完成":
        return
    sync_sku_dev_stage(db, sku_code, "套图制作中")
    if not data.get("finished_at"):
        new_data = dict(data)
        new_data["finished_at"] = datetime.date.today().isoformat()
        record.data = new_data
        db.add(record)


def spawn_set_task_if_needed(db: Session, record: Record, creator_id: int) -> None:
    """AI主图任务已完成时自动生成套图任务（幂等：同一条任务只会触发一次）。"""
    data = record.data or {}
    if data.get("status") != "已完成" or data.get("_spawned_set_task"):
        return
    sku_code = data.get("related_sku")
    sku_record = find_sku_by_code(db, sku_code)
    sku_categories = (sku_record.data or {}).get("category") if sku_record else None
    set_data = {
        "task_code": generate_task_code(db, "set_task"),
        "related_sku": sku_code,
        "status": "待制作",
        "maker": assign_round_robin(db, "set_task", sku_categories) or "",
        "competitor_link": data.get("competitor_link", ""),
        "priority": (sku_record.data or {}).get("priority", 0) if sku_record else data.get("priority", 0),
        "created_at": datetime.date.today().isoformat(),
    }
    _create_record(db, "set_task", set_data, creator_id)
    new_data = dict(data)
    new_data["_spawned_set_task"] = True
    record.data = new_data
    db.add(record)


def on_set_task_saved(db: Session, record: Record, previous_status: Optional[str], creator_id: int) -> None:
    """同上：先只做同步开发阶段 + 记录完成时间，生成下游上架任务放到
    spawn_pending_listing_if_needed 里单独处理。"""
    data = record.data or {}
    status = data.get("status")
    sku_code = data.get("related_sku")
    if status == previous_status:
        return
    if status in ("待制作", "制作中"):
        sync_sku_dev_stage(db, sku_code, "套图制作中")
        return
    if status != "已完成":
        return
    sync_sku_dev_stage(db, sku_code, "待上架")
    if not data.get("finished_at"):
        new_data = dict(data)
        new_data["finished_at"] = datetime.date.today().isoformat()
        record.data = new_data
        db.add(record)


def spawn_pending_listing_if_needed(db: Session, record: Record, creator_id: int) -> None:
    """套图任务已完成时自动生成上架任务（幂等：同一条任务只会触发一次）。"""
    data = record.data or {}
    if data.get("status") != "已完成" or data.get("_spawned_pending"):
        return
    sku_code = data.get("related_sku")
    shop_fields = assign_shop_fields_for_create(db, sku_code)
    pending_data = {
        "task_code": generate_task_code(db, "pending_listing"),
        "note": f"套图任务完成自动创建 - SKU: {sku_code}",
        "is_listed": False,
        "shop_name": shop_fields["shop_name"],
        "shop_owner": shop_fields["shop_owner"],
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
        if not data.get("finished_at"):
            new_data = dict(data)
            new_data["finished_at"] = datetime.date.today().isoformat()
            record.data = new_data
            db.add(record)
    else:
        sync_sku_dev_stage(db, sku_code, "待上架")


# ---------------- 三期：历史归档 ----------------

_ARCHIVE_MAP = {
    "sku": "archive_sku",
    "ai_creative": "archive_ai_creative",
    "set_task": "archive_set_task",
    "pending_listing": "archive_pending_listing",
}


def _archive_one(record: Record, dst_key: str, archived_at: str) -> None:
    data = dict(record.data or {})
    data["archived_at"] = archived_at
    record.table_key = dst_key
    record.data = data


def run_archive_if_needed(db: Session, threshold: int = 200, keep_recent: int = 100) -> int:
    """
    已上架 SKU 数量达到 threshold 时，把最早上架的一批 SKU（连同它们在各任务表里的
    所有相关记录）搬去历史归档表，只在工作表里保留最近 keep_recent 个，减少活跃表的查询压力。
    返回本次归档的 SKU 数量。任何一个 SKU 归档失败都不影响其它 SKU 继续归档。
    """
    pending_records = _all_records(db, "pending_listing")
    listed = [r for r in pending_records if (r.data or {}).get("is_listed") in (True, "true")]
    if len(listed) < threshold:
        return 0

    def sort_key(r):
        d = r.data or {}
        return d.get("finished_at") or d.get("created_at") or ""

    listed.sort(key=sort_key)
    to_archive_count = len(listed) - keep_recent
    if to_archive_count <= 0:
        return 0

    archived_at = datetime.date.today().isoformat()
    archived_count = 0
    for pending_rec in listed[:to_archive_count]:
        sku_code = (pending_rec.data or {}).get("related_sku")
        if not sku_code:
            continue
        try:
            with db.begin_nested():  # SAVEPOINT：这个SKU出错只回滚它自己，不影响同一批里已经归档成功的其它SKU
                sku_rec = find_sku_by_code(db, sku_code)
                if sku_rec:
                    _archive_one(sku_rec, _ARCHIVE_MAP["sku"], archived_at)
                    db.add(sku_rec)
                for src_key in ("ai_creative", "set_task", "pending_listing"):
                    for r in _all_records(db, src_key):
                        if (r.data or {}).get("related_sku") == sku_code:
                            _archive_one(r, _ARCHIVE_MAP[src_key], archived_at)
                            db.add(r)
            archived_count += 1
        except Exception:
            logger.exception("[archive] SKU %s 归档失败，已跳过，继续归档同一批里的其它SKU", sku_code)
            continue
    return archived_count
