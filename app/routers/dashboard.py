import datetime
from collections import defaultdict
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Record, User
from ..security import get_current_user
from .. import automation

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

STATUS_OPTIONS = ["待制作", "制作中", "已完成"]


def _records(db: Session, table_key: str):
    return db.query(Record).filter(Record.table_key == table_key).all()


def _status_count(records, status_val):
    return sum(1 for r in records if (r.data or {}).get("status") == status_val)


def _status_pivot(records, group_field):
    """按 制作人 分组统计 待制作/制作中/已完成 各多少条，附带每行总计。"""
    pivot = defaultdict(lambda: {s: 0 for s in STATUS_OPTIONS})
    for r in records:
        d = r.data or {}
        status = d.get("status")
        if status not in STATUS_OPTIONS:
            continue
        group_val = (d.get(group_field) or "").strip() or "未分配"
        pivot[group_val][status] += 1
    rows = []
    for name in sorted(pivot.keys()):
        counts = pivot[name]
        rows.append({"name": name, **counts, "total": sum(counts.values())})
    return rows


def _bool_pivot(records, group_field):
    """按 店铺负责人 分组统计 已上架/未上架 各多少条。"""
    pivot = defaultdict(lambda: {"false": 0, "true": 0})
    for r in records:
        d = r.data or {}
        group_val = (d.get(group_field) or "").strip() or "未分配"
        key = "true" if d.get("is_listed") in (True, "true") else "false"
        pivot[group_val][key] += 1
    rows = []
    for name in sorted(pivot.keys()):
        c = pivot[name]
        rows.append({"name": name, "false": c["false"], "true": c["true"], "total": c["false"] + c["true"]})
    return rows


def _iso(offset_days: int = 0) -> str:
    return (datetime.date.today() - datetime.timedelta(days=offset_days)).isoformat()


def _task_today_stats(records, today: str, yesterday: str):
    current = sum(1 for r in records if (r.data or {}).get("status") in ("待制作", "制作中"))
    completed_today = sum(1 for r in records if (r.data or {}).get("finished_at") == today)
    created_yesterday = sum(1 for r in records if (r.data or {}).get("created_at") == yesterday)
    completed_yesterday = sum(1 for r in records if (r.data or {}).get("finished_at") == yesterday)
    return {
        "current": current, "completed_today": completed_today,
        "created_yesterday": created_yesterday, "completed_yesterday": completed_yesterday,
    }


def _pending_today_stats(records, today: str, yesterday: str):
    def is_listed(d):
        return d.get("is_listed") in (True, "true")

    current = sum(1 for r in records if not is_listed(r.data or {}))
    completed_today = sum(
        1 for r in records if is_listed(r.data or {}) and (r.data or {}).get("finished_at") == today
    )
    created_yesterday = sum(1 for r in records if (r.data or {}).get("created_at") == yesterday)
    completed_yesterday = sum(
        1 for r in records if is_listed(r.data or {}) and (r.data or {}).get("finished_at") == yesterday
    )
    return {
        "current": current, "completed_today": completed_today,
        "created_yesterday": created_yesterday, "completed_yesterday": completed_yesterday,
    }


def _month_prefix() -> str:
    return datetime.date.today().strftime("%Y-%m")


def _monthly_leaderboard(records, group_field: str, is_done) -> list:
    """按“负责人”统计本月完成数量并按完成数从高到低排名。is_done 是判断一条记录
    是否算“完成”的函数；只统计 finished_at 落在本月的记录。"""
    month_prefix = _month_prefix()
    counts = defaultdict(int)
    for r in records:
        d = r.data or {}
        finished_at = d.get("finished_at") or ""
        if not finished_at.startswith(month_prefix):
            continue
        if not is_done(d):
            continue
        name = (d.get(group_field) or "").strip() or "未分配"
        counts[name] += 1
    ranking = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"name": name, "count": count} for name, count in ranking]


def _category_distribution_today(db: Session, ai_records, set_records, pending_records) -> dict:
    """
    当日（按创建时间）AI主图/套图/上架 这三张任务表里，按 SKU 品类统计任务数量分布，
    图例标签把品类对应的店铺名一起带出来（比如"数字产品（ShopA）"），方便一眼看出
    今天这些任务分别属于哪个品类、又会流向哪个店铺。
    一个 SKU 可能同时属于多个品类，这种情况下会计入它所属的每一个品类。
    """
    today = _iso(0)
    all_records = list(ai_records) + list(set_records) + list(pending_records)
    counts = defaultdict(int)
    sku_cache = {}
    for r in all_records:
        d = r.data or {}
        if d.get("created_at") != today:
            continue
        sku_code = d.get("related_sku")
        if not sku_code:
            continue
        if sku_code not in sku_cache:
            sku_cache[sku_code] = automation.find_sku_by_code(db, sku_code)
        sku_record = sku_cache[sku_code]
        if not sku_record:
            continue
        categories = (sku_record.data or {}).get("category")
        if isinstance(categories, str):
            categories = [categories]
        for cat in (categories or []):
            cat = (cat or "").strip()
            if cat:
                counts[cat] += 1

    labeled = defaultdict(int)
    for cat, count in counts.items():
        shop_name, _owner = automation.resolve_shop_for_category(db, [cat])
        label = f"{cat}（{shop_name}）" if shop_name else cat
        labeled[label] += count
    return dict(labeled)


@router.get("/summary")
def dashboard_summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ai_records = _records(db, "ai_creative")
    set_records = _records(db, "set_task")
    pending_records = _records(db, "pending_listing")

    today = _iso(0)
    yesterday = _iso(1)

    listed_count = sum(1 for r in pending_records if (r.data or {}).get("is_listed") in (True, "true"))

    totals = {
        "ai_creative": {"total": len(ai_records), "done": _status_count(ai_records, "已完成")},
        "set_task": {"total": len(set_records), "done": _status_count(set_records, "已完成")},
        "pending_listing": {"total": len(pending_records), "listed": listed_count},
    }

    by_maker = {
        "ai_creative": _status_pivot(ai_records, "maker"),
        "set_task": _status_pivot(set_records, "maker"),
    }
    by_owner = {"pending_listing": _bool_pivot(pending_records, "shop_owner")}

    today_block = {
        "ai_creative": _task_today_stats(ai_records, today, yesterday),
        "set_task": _task_today_stats(set_records, today, yesterday),
        "pending_listing": _pending_today_stats(pending_records, today, yesterday),
    }

    leaderboards = {
        "ai_creative": _monthly_leaderboard(ai_records, "maker", lambda d: d.get("status") == "已完成"),
        "set_task": _monthly_leaderboard(set_records, "maker", lambda d: d.get("status") == "已完成"),
        "pending_listing": _monthly_leaderboard(
            pending_records, "shop_owner", lambda d: d.get("is_listed") in (True, "true")
        ),
    }

    shop_distribution_today = _category_distribution_today(db, ai_records, set_records, pending_records)

    return {
        "totals": totals,
        "by_maker": by_maker,
        "by_owner": by_owner,
        "today": today_block,
        "leaderboards": leaderboards,
        "shop_distribution_today": shop_distribution_today,
        "generated_at": datetime.datetime.utcnow().isoformat(),
    }
