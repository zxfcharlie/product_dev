from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session
from pydantic import BaseModel

from ..database import get_db
from ..models import User
from ..security import hash_password, verify_password, create_access_token, get_current_user, COOKIE_SECURE

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
        # 第一个账号（自动成为管理员）直接放行；其它人注册后要等管理员审核通过才能登录，
        # 避免任何人注册个账号就能直接进来操作数据。
        is_approved=is_first_user,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {
        "id": user.id, "username": user.username, "role": user.role,
        "is_approved": user.is_approved,
    }


@router.post("/login")
def login(payload: LoginIn, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")
    if not user.is_approved:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "账号还在等待管理员审核，审核通过后才能登录")
    token = create_access_token({"uid": user.id})
    response.set_cookie(
        key="access_token", value=token, httponly=True,
        max_age=60 * 60 * 24 * 7, samesite="lax", secure=COOKIE_SECURE,
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
