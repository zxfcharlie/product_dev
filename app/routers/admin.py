from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from ..database import get_db
from ..models import User
from ..security import require_admin

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
