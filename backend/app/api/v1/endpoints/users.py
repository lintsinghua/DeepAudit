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
    获取用户列表（支持分页、搜索、筛选）
    """
    query = select(User)
    count_query = select(func.count(User.id))
    
    # 搜索条件
    if search:
        search_filter = or_(
            User.email.ilike(f"%{search}%"),
            User.full_name.ilike(f"%{search}%"),
            User.phone.ilike(f"%{search}%")
        )
        query = query.where(search_filter)
        count_query = count_query.where(search_filter)
    
    # 角色筛选
    if role:
        query = query.where(User.role == role)
        count_query = count_query.where(User.role == role)
    
    # 状态筛选
    if is_active is not None:
        query = query.where(User.is_active == is_active)
        count_query = count_query.where(User.is_active == is_active)
    
    # 获取总数
    total_result = await db.execute(count_query)
    total = total_result.scalar()
    
    # 分页查询
    query = query.order_by(User.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    users = result.scalars().all()
    
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
    创建新用户（仅管理员）
    """
    result = await db.execute(select(User).where(User.email == user_in.email))
    user = result.scalars().first()
    if user:
        raise HTTPException(
            status_code=400,
            detail="该邮箱已被注册",
        )
    
    db_user = User(
        email=user_in.email,
        hashed_password=security.get_password_hash(user_in.password),
        full_name=user_in.full_name,
        phone=user_in.phone,
        role=user_in.role,
        is_active=user_in.is_active if user_in.is_active is not None else True,
        is_superuser=user_in.is_superuser if user_in.is_superuser is not None else False,
    )
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user

@router.get("/me", response_model=UserSchema)
async def read_user_me(
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    获取当前用户信息
    """
    return current_user

@router.put("/me", response_model=UserSchema)
async def update_user_me(
    *,
    db: AsyncSession = Depends(get_db),
    user_in: UserUpdate,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    更新当前用户信息
    """
    update_data = user_in.model_dump(exclude_unset=True)
    
    # 普通用户不能修改自己的角色和超级管理员状态
    update_data.pop('role', None)
    update_data.pop('is_superuser', None)
    update_data.pop('is_active', None)
    
    # 如果更新密码
    if 'password' in update_data and update_data['password']:
        update_data['hashed_password'] = security.get_password_hash(update_data['password'])
    update_data.pop('password', None)
    
    for field, value in update_data.items():
        setattr(current_user, field, value)
    
    await db.commit()
    await db.refresh(current_user)
    return current_user

@router.get("/{user_id}", response_model=UserSchema)
async def read_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    获取指定用户信息
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
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
    更新用户信息（仅管理员）
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    update_data = user_in.model_dump(exclude_unset=True)
    
    # 如果更新密码
    if 'password' in update_data and update_data['password']:
        update_data['hashed_password'] = security.get_password_hash(update_data['password'])
    update_data.pop('password', None)
    
    for field, value in update_data.items():
        setattr(user, field, value)
    
    await db.commit()
    await db.refresh(user)
    return user

@router.delete("/{user_id}")
async def delete_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_superuser),
) -> Any:
    """
    删除用户（仅管理员）
    """
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能删除自己的账户")
    
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    await db.delete(user)
    await db.commit()
    return {"message": "用户已删除"}

@router.post("/{user_id}/toggle-status", response_model=UserSchema)
async def toggle_user_status(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_superuser),
) -> Any:
    """
    切换用户状态（启用/禁用）
    """
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能禁用自己的账户")
    
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    user.is_active = not user.is_active
    await db.commit()
    await db.refresh(user)
    return user






