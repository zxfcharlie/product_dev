from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from ..database import get_db
from ..models import User
from ..security import require_admin
from .. import automation

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users")
def list_users(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    users = db.query(User).order_by(User.id.asc()).all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "display_name": u.display_name,
            "role": u.role,
            "note": u.note or "",
            "is_active": u.is_active,
            "is_approved": u.is_approved,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in users
    ]


class UserNoteIn(BaseModel):
    note: str


@router.put("/users/{user_id}/note")
def update_user_note(user_id: int, payload: UserNoteIn, db: Session = Depends(get_db),
                      admin: User = Depends(require_admin)):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, "用户不存在")
    u.note = payload.note
    db.commit()
    return {"ok": True}


class ApprovalIn(BaseModel):
    approved: bool


@router.put("/users/{user_id}/approve")
def set_user_approval(user_id: int, payload: ApprovalIn, db: Session = Depends(get_db),
                       admin: User = Depends(require_admin)):
    if user_id == admin.id and not payload.approved:
        raise HTTPException(400, "不能取消自己的审核状态")
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, "用户不存在")
    u.is_approved = payload.approved
    db.commit()
    return {"ok": True, "is_approved": u.is_approved}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if user_id == admin.id:
        raise HTTPException(400, "不能删除自己")
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, "用户不存在")
    if u.role == "admin":
        remaining_admins = db.query(User).filter(User.role == "admin").count()
        if remaining_admins <= 1:
            raise HTTPException(400, "至少需要保留一个管理员账号，不能删除")
    db.delete(u)
    db.commit()
    return {"ok": True}


@router.post("/run-archive")
def run_archive_now(force: bool = False, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """
    手动触发一次归档检查。force=False（默认）只有已上架SKU达到200个才会真的归档；
    force=True 忽略这个门槛，只要有已上架SKU超过保留数量(100)就归档，方便测试/立即清理。
    """
    threshold = 0 if force else 200
    count = automation.run_archive_if_needed(db, threshold=threshold, keep_recent=100)
    db.commit()
    return {"archived_skus": count}
