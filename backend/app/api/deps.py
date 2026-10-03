"""
模块说明：API 路由与依赖定义：deps。
"""

from typing import Generator, Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.core import security
from app.core.config import settings
from app.db.session import get_db
from app.models.user import User
from app.schemas import token as token_schema

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login"
)

async def get_current_user(
    db: AsyncSession = Depends(get_db),
    token: str = Depends(reusable_oauth2)
) -> User:
    """
    从请求令牌解析并返回当前用户。

    处理流程：
    - 解析并校验 JWT
    - 构建 TokenPayload
    - 查询用户并校验状态
    """
    # 解析并验证 JWT
    try:
        # 解码令牌载荷
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
        )
        # 将载荷解析为结构化数据
        token_data = token_schema.TokenPayload(**payload)
    except (JWTError, ValidationError):
        # 令牌无效或格式不正确时返回 401
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无法验证凭据",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # 查询用户记录
    result = await db.execute(select(User).where(User.id == token_data.sub))
    # 提取用户对象
    user = result.scalars().first()
    # 若用户不存在则返回 404
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    # 若用户已被禁用则返回 400
    if not user.is_active:
        raise HTTPException(status_code=400, detail="用户已被禁用")
    # 返回当前用户
    return user

async def get_current_active_superuser(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    校验当前用户是否为超级管理员。

    处理流程：
    - 依赖注入获取当前用户
    - 检查超级管理员标识
    """
    # 若非超级管理员则拒绝访问
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=400, detail="权限不足"
        )
    # 返回通过校验的用户
    return current_user
