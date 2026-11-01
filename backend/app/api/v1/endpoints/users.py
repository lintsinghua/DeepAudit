"""
模块说明：API 路由与依赖定义：users。
"""

from typing import Any, List, Optional
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, or_

from app.api import deps
from app.core import security
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import User as UserSchema, UserCreate, UserUpdate, UserListResponse

router = APIRouter()

@router.get("/", response_model=UserListResponse)
async def read_users(
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None, description="搜索关键词"),
    role: Optional[str] = Query(None, description="角色筛选"),
    is_active: Optional[bool] = Query(None, description="状态筛选"),
    current_user: User = Depends(deps.get_current_active_superuser),
) -> Any:
    """
    获取用户列表（支持分页、搜索、筛选）。

    处理流程：
    - 构建基础查询与计数查询
    - 根据搜索、角色、状态追加过滤条件
    - 计算总数
    - 执行分页查询并返回结果
    """
    # 基础查询：获取用户
    query = select(User)
    # 统计查询：获取总数
    count_query = select(func.count(User.id))
    # 追加搜索条件
    if search:
        # 构建模糊搜索过滤条件
        search_filter = or_(
            User.email.ilike(f"%{search}%"),
            User.full_name.ilike(f"%{search}%"),
            User.phone.ilike(f"%{search}%")
        )
        # 将搜索条件应用到数据查询
        query = query.where(search_filter)
        # 将搜索条件应用到统计查询
        count_query = count_query.where(search_filter)
    # 追加角色筛选
    if role:
        # 限定角色
        query = query.where(User.role == role)
        # 限定统计范围
        count_query = count_query.where(User.role == role)
    # 追加状态筛选
    if is_active is not None:
        # 限定启用状态
        query = query.where(User.is_active == is_active)
        # 限定统计范围
        count_query = count_query.where(User.is_active == is_active)
    # 执行统计查询
    total_result = await db.execute(count_query)
    # 取出总数
    total = total_result.scalar()
    # 应用排序与分页
    query = query.order_by(User.created_at.desc()).offset(skip).limit(limit)
    # 执行数据查询
    result = await db.execute(query)
    # 取出用户列表
    users = result.scalars().all()
    # 返回分页结果
    return {
        "users": users,
        "total": total,
        "skip": skip,
        "limit": limit
    }

@router.post("/", response_model=UserSchema)
async def create_user(
    *,
    db: AsyncSession = Depends(get_db),
    user_in: UserCreate,
    current_user: User = Depends(deps.get_current_active_superuser),
) -> Any:
    """
    创建新用户（仅管理员）。

    处理流程：
    - 校验邮箱是否已被注册
    - 构建用户对象并写入数据库
    """
    # 检查邮箱是否已存在
    result = await db.execute(select(User).where(User.email == user_in.email))
    # 提取已有用户
    user = result.scalars().first()
    # 若已存在则返回 400
    if user:
        raise HTTPException(
            status_code=400,
            detail="该邮箱已被注册",
        )
    # 构建用户对象
    db_user = User(
        # 邮箱
        email=user_in.email,
        # 密码哈希
        hashed_password=security.get_password_hash(user_in.password),
        # 显示名
        full_name=user_in.full_name,
        # 手机号
        phone=user_in.phone,
        # 角色
        role=user_in.role,
        # 是否启用
        is_active=user_in.is_active if user_in.is_active is not None else True,
        # 是否超级管理员
        is_superuser=user_in.is_superuser if user_in.is_superuser is not None else False,
    )
    # 写入数据库
    db.add(db_user)
    # 提交事务
    await db.commit()
    # 刷新对象
    await db.refresh(db_user)
    # 返回创建结果
    return db_user

@router.get("/me", response_model=UserSchema)
async def read_user_me(
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    获取当前用户信息。

    处理流程：
    - 依赖注入获取当前用户
    - 直接返回用户对象
    """
    # 返回当前用户
    return current_user

@router.put("/me", response_model=UserSchema)
async def update_user_me(
    *,
    db: AsyncSession = Depends(get_db),
    user_in: UserUpdate,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    更新当前用户信息。

    处理流程：
    - 提取可更新字段
    - 移除普通用户不可修改字段
    - 处理密码更新
    - 写入数据库并返回
    """
    # 获取请求中的可更新字段
    update_data = user_in.model_dump(exclude_unset=True)
    # 移除普通用户不可修改的字段
    update_data.pop('role', None)
    update_data.pop('is_superuser', None)
    update_data.pop('is_active', None)
    # 如果包含密码则进行哈希处理
    if 'password' in update_data and update_data['password']:
        update_data['hashed_password'] = security.get_password_hash(update_data['password'])
    # 移除明文密码字段
    update_data.pop('password', None)
    # 将更新字段写入当前用户对象
    for field, value in update_data.items():
        setattr(current_user, field, value)
    # 提交事务
    await db.commit()
    # 刷新对象
    await db.refresh(current_user)
    # 返回更新结果
    return current_user

@router.get("/{user_id}", response_model=UserSchema)
async def read_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    获取指定用户信息。

    处理流程：
    - 根据用户 ID 查询用户
    - 不存在则返回 404
    - 返回用户信息
    """
    # 按用户 ID 查询
    result = await db.execute(select(User).where(User.id == user_id))
    # 提取用户对象
    user = result.scalars().first()
    # 若用户不存在则返回 404
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    # 返回用户
    return user

@router.put("/{user_id}", response_model=UserSchema)
async def update_user(
    user_id: str,
    *,
    db: AsyncSession = Depends(get_db),
    user_in: UserUpdate,
    current_user: User = Depends(deps.get_current_active_superuser),
) -> Any:
    """
    更新用户信息（仅管理员）。

    处理流程：
    - 查询目标用户
    - 提取更新字段
    - 处理密码更新
    - 写入数据库并返回
    """
    # 查询目标用户
    result = await db.execute(select(User).where(User.id == user_id))
    # 提取用户对象
    user = result.scalars().first()
    # 若用户不存在则返回 404
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    # 获取请求中的可更新字段
    update_data = user_in.model_dump(exclude_unset=True)
    # 如果包含密码则进行哈希处理
    if 'password' in update_data and update_data['password']:
        update_data['hashed_password'] = security.get_password_hash(update_data['password'])
    # 移除明文密码字段
    update_data.pop('password', None)
    # 写入更新字段
    for field, value in update_data.items():
        setattr(user, field, value)
    # 提交事务
    await db.commit()
    # 刷新对象
    await db.refresh(user)
    # 返回更新结果
    return user

@router.delete("/{user_id}")
async def delete_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_superuser),
) -> Any:
    """
    删除用户（仅管理员）。

    处理流程：
    - 禁止删除自身
    - 查询目标用户
    - 删除用户并提交
    """
    # 禁止删除自己的账户
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能删除自己的账户")
    # 查询目标用户
    result = await db.execute(select(User).where(User.id == user_id))
    # 提取用户对象
    user = result.scalars().first()
    # 若用户不存在则返回 404
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    # 删除用户
    await db.delete(user)
    # 提交事务
    await db.commit()
    # 返回删除结果
    return {"message": "用户已删除"}

@router.post("/{user_id}/toggle-status", response_model=UserSchema)
async def toggle_user_status(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_superuser),
) -> Any:
    """
    切换用户状态（启用/禁用）。

    处理流程：
    - 禁止禁用自身账户
    - 查询目标用户
    - 切换启用状态并保存
    """
    # 禁止禁用自己的账户
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能禁用自己的账户")
    # 查询目标用户
    result = await db.execute(select(User).where(User.id == user_id))
    # 提取用户对象
    user = result.scalars().first()
    # 若用户不存在则返回 404
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    # 切换启用状态
    user.is_active = not user.is_active
    # 提交事务
    await db.commit()
    # 刷新对象
    await db.refresh(user)
    # 返回更新结果
    return user





