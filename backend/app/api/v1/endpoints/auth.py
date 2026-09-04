"""
模块说明：API 路由与依赖定义：auth。
"""

from datetime import timedelta
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from pydantic import BaseModel, EmailStr

from app.api import deps
from app.core import security
from app.core.config import settings
from app.db.session import get_db
from app.models.user import User
from app.schemas.token import Token
from app.schemas.user import User as UserSchema, UserCreate

router = APIRouter()

class RegisterRequest(BaseModel):
    """注册请求体模型。"""
    email: EmailStr
    password: str
    full_name: str

@router.post("/login", response_model=Token)
async def login(
    db: AsyncSession = Depends(get_db),
    form_data: OAuth2PasswordRequestForm = Depends()
) -> Any:
    """
    OAuth2 兼容登录，返回访问令牌。

    处理流程：
    - 通过邮箱查找用户
    - 校验密码与用户状态
    - 生成并返回访问令牌
    """
    # 按邮箱查询用户
    result = await db.execute(select(User).where(User.email == form_data.username))
    # 取出用户对象
    user = result.scalars().first()
    # 校验用户存在性与密码正确性
    if not user or not security.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="邮箱或密码错误")
    # 校验用户是否被禁用
    elif not user.is_active:
        raise HTTPException(status_code=400, detail="用户已被禁用")
    # 计算访问令牌过期时间
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    # 返回访问令牌与类型
    return {
        # 创建访问令牌
        "access_token": security.create_access_token(
            user.id, expires_delta=access_token_expires
        ),
        # 固定令牌类型
        "token_type": "bearer",
    }

@router.post("/register", response_model=UserSchema)
async def register(
    *,
    db: AsyncSession = Depends(get_db),
    user_in: RegisterRequest,
) -> Any:
    """
    注册新用户。

    处理流程：
    - 检查邮箱是否已被注册
    - 判断是否为首个用户
    - 创建用户并设置角色
    """
    # 检查邮箱是否已存在
    result = await db.execute(select(User).where(User.email == user_in.email))
    # 提取已存在用户
    existing_user = result.scalars().first()
    # 若已存在则返回 400
    if existing_user:
        raise HTTPException(
            status_code=400,
            detail="该邮箱已被注册",
        )
    # 查询用户总数，用于判断是否首个用户
    count_result = await db.execute(select(User))
    # 取出全部用户
    all_users = count_result.scalars().all()
    # 判断首个用户
    is_first_user = len(all_users) == 0
    # 构建新用户对象
    db_user = User(
        # 邮箱
        email=user_in.email,
        # 密码哈希
        hashed_password=security.get_password_hash(user_in.password),
        # 显示名
        full_name=user_in.full_name,
        # 启用用户
        is_active=True,
        # 首个用户设为超级管理员
        is_superuser=is_first_user,
        # 首个用户设为 admin 角色
        role="admin" if is_first_user else "member",
    )
    # 写入数据库
    db.add(db_user)
    # 提交事务
    await db.commit()
    # 刷新对象以获取数据库生成字段
    await db.refresh(db_user)
    # 返回新用户
    return db_user
