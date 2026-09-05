import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, ForeignKey, DateTime, Text
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, index=True, nullable=False)
    display_name = Column(String(64), nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(16), nullable=False, default="member")  # admin | member
    is_active = Column(Boolean, default=True)
    is_approved = Column(Boolean, default=False)  # 新注册账号默认未审核，管理员批准后才能登录
    note = Column(Text, nullable=True, default="")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class Record(Base):
    """
    通用记录表：每一行代表某张业务表(table_key)中的一条记录。
    真正的业务字段全部放在 data(JSONB) 里，字段结构由 app/schemas_config.py 定义。
    这样新增/修改字段不需要改数据库结构，符合多维表格类产品的设计思路。
    """
    __tablename__ = "records"

    id = Column(Integer, primary_key=True, index=True)
    table_key = Column(String(64), index=True, nullable=False)
    data = Column(JSONB, nullable=False, default=dict)
    creator_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    creator = relationship("User")


class SavedView(Base):
    """
    每张表可以有多个视图（对应截图里的 Grid / 过去7天上架 / 正在制作 等 tab）。
    filters / sorts 用 JSON 存储筛选和排序规则。
    """
    __tablename__ = "saved_views"

    id = Column(Integer, primary_key=True, index=True)
    table_key = Column(String(64), index=True, nullable=False)
    name = Column(String(64), nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"))
    filters = Column(JSONB, default=list)   # [{field, op, value}, ...]
    sorts = Column(JSONB, default=list)     # [{field, dir}, ...]
    is_shared = Column(Boolean, default=True)  # 团队共享还是仅自己可见
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
