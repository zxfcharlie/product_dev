import datetime
from collections import defaultdict
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Record, User
from ..security import get_current_user

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

    status_distribution = {
        "ai_creative": {s: _status_count(ai_records, s) for s in STATUS_OPTIONS},
        "set_task": {s: _status_count(set_records, s) for s in STATUS_OPTIONS},
        "pending_listing": {
            "已上架": listed_count,
            "待上架": totals["pending_listing"]["total"] - listed_count,
        },
    }

    return {
        "totals": totals,
        "by_maker": by_maker,
        "by_owner": by_owner,
        "today": today_block,
        "status_distribution": status_distribution,
        "generated_at": datetime.datetime.utcnow().isoformat(),
    }
