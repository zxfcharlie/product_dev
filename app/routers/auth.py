from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session
from pydantic import BaseModel

from ..database import get_db
from ..models import User, Record, SavedView
from ..security import hash_password, verify_password, create_access_token, get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterIn(BaseModel):
    username: str
    password: str
    display_name: str


class LoginIn(BaseModel):
    username: str
    password: str


@router.post("/register")
def register(payload: RegisterIn, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(400, "用户名已存在")
    is_first_user = db.query(User).count() == 0
    user = User(
        username=payload.username,
        display_name=payload.display_name,
        hashed_password=hash_password(payload.password),
        role="admin" if is_first_user else "member",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"id": user.id, "username": user.username, "role": user.role}


@router.post("/login")
def login(payload: LoginIn, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")
    token = create_access_token({"uid": user.id})
    response.set_cookie(
        key="access_token", value=token, httponly=True,
        max_age=60 * 60 * 24 * 7, samesite="lax",
    )
    return {"id": user.id, "username": user.username, "display_name": user.display_name, "role": user.role}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("access_token")
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {
        "id": user.id, "username": user.username,
        "display_name": user.display_name, "role": user.role,
    }

class UserNoteIn(BaseModel):
    note: str = ""


def _require_admin(user: User):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可管理用户")


@router.get("/users")
def list_users(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_admin(user)
    rows = db.query(User).order_by(User.id.asc()).all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "display_name": u.display_name,
            "role": u.role,
            "is_active": u.is_active,
            "note": u.note or "",
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in rows
    ]


@router.put("/users/{user_id}/note")
def update_user_note(user_id: int, payload: UserNoteIn, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    _require_admin(user)
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(404, "用户不存在")
    target.note = payload.note.strip()
    db.add(target)
    db.commit()
    return {"ok": True, "note": target.note or ""}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_admin(user)
    if user_id == user.id:
        raise HTTPException(400, "不能删除当前登录的管理员账号")
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(404, "用户不存在")
    if target.role == "admin" and db.query(User).filter(User.role == "admin").count() <= 1:
        raise HTTPException(400, "系统至少需要保留一个管理员")
    # 保留该用户历史业务数据/视图，但解除外键归属，再删除账号。
    db.query(Record).filter(Record.creator_id == target.id).update({Record.creator_id: None}, synchronize_session=False)
    db.query(SavedView).filter(SavedView.owner_id == target.id).update({SavedView.owner_id: None}, synchronize_session=False)
    db.delete(target)
    db.commit()
    return {"ok": True}
