"""
模块说明：API 路由与依赖定义：members。
"""

from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from pydantic import BaseModel
from datetime import datetime

from app.api import deps
from app.db.session import get_db
from app.models.project import Project, ProjectMember
from app.models.user import User

router = APIRouter()


class UserSchema(BaseModel):
    """用户基础信息的响应模型。"""
    id: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    role: Optional[str] = None

    class Config:
        from_attributes = True


class ProjectMemberSchema(BaseModel):
    """项目成员的响应模型，包含用户信息。"""
    id: str
    project_id: str
    user_id: str
    role: str
    permissions: Optional[str] = None
    joined_at: datetime
    created_at: datetime
    user: Optional[UserSchema] = None

    class Config:
        from_attributes = True


class AddMemberRequest(BaseModel):
    """新增项目成员的请求体模型。"""
    user_id: str
    role: str = "member"


class UpdateMemberRequest(BaseModel):
    """更新项目成员角色与权限的请求体模型。"""
    role: Optional[str] = None
    permissions: Optional[str] = None


@router.get("/{project_id}/members", response_model=List[ProjectMemberSchema])
async def get_project_members(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    获取指定项目的成员列表。

    处理流程：
    - 校验项目是否存在
    - 查询成员并加载关联用户信息
    - 按加入时间倒序返回
    """
    # 读取项目，确认项目是否存在
    project = await db.get(Project, project_id)
    # 若项目不存在则返回 404
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    # 查询项目成员并预加载用户信息
    result = await db.execute(
        # 构造成员查询
        select(ProjectMember)
        # 预加载 user 关联，避免 N+1
        .options(selectinload(ProjectMember.user))
        # 过滤当前项目
        .where(ProjectMember.project_id == project_id)
        # 按加入时间倒序
        .order_by(ProjectMember.joined_at.desc())
    )
    # 返回成员列表
    return result.scalars().all()


@router.post("/{project_id}/members", response_model=ProjectMemberSchema)
async def add_project_member(
    project_id: str,
    member_in: AddMemberRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    向指定项目添加成员。

    处理流程：
    - 校验项目是否存在
    - 校验当前用户权限
    - 校验目标用户是否存在
    - 校验是否已是成员
    - 创建成员记录并返回
    """
    # 读取项目，确认项目是否存在
    project = await db.get(Project, project_id)
    # 若项目不存在则返回 404
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    # 校验当前用户是否为项目所有者或超级管理员
    if project.owner_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="权限不足")
    # 读取目标用户，确认用户是否存在
    user = await db.get(User, member_in.user_id)
    # 若用户不存在则返回 404
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    # 查询是否已存在成员记录
    existing = await db.execute(
        # 构造成员查询条件
        select(ProjectMember)
        # 同时匹配项目与用户
        .where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == member_in.user_id
        )
    )
    # 若已有成员记录则返回 400
    if existing.scalars().first():
        raise HTTPException(status_code=400, detail="用户已是项目成员")
    # 构建成员记录
    member = ProjectMember(
        # 绑定项目
        project_id=project_id,
        # 绑定用户
        user_id=member_in.user_id,
        # 角色信息
        role=member_in.role,
        # 权限 JSON 字符串占位
        permissions="{}"
    )
    # 追加到会话
    db.add(member)
    # 提交事务
    await db.commit()
    # 刷新以获取数据库生成字段
    await db.refresh(member)
    # 重新加载成员并预加载用户关系
    result = await db.execute(
        # 构造成员查询
        select(ProjectMember)
        # 预加载 user 关联
        .options(selectinload(ProjectMember.user))
        # 根据成员 ID 定位
        .where(ProjectMember.id == member.id)
    )
    # 返回新成员
    return result.scalars().first()


@router.put("/{project_id}/members/{member_id}", response_model=ProjectMemberSchema)
async def update_project_member(
    project_id: str,
    member_id: str,
    member_update: UpdateMemberRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    更新项目成员的角色或权限。

    处理流程：
    - 校验项目是否存在
    - 校验当前用户权限
    - 获取成员记录
    - 更新字段并保存
    - 返回更新后的成员信息
    """
    # 读取项目，确认项目是否存在
    project = await db.get(Project, project_id)
    # 若项目不存在则返回 404
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    # 校验当前用户是否为项目所有者或超级管理员
    if project.owner_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="权限不足")
    # 查询目标成员记录
    result = await db.execute(
        # 构造成员查询
        select(ProjectMember)
        # 同时匹配成员与项目
        .where(ProjectMember.id == member_id, ProjectMember.project_id == project_id)
    )
    # 获取成员对象
    member = result.scalars().first()
    # 若成员不存在则返回 404
    if not member:
        raise HTTPException(status_code=404, detail="成员不存在")
    # 如果传入角色则更新角色
    if member_update.role:
        member.role = member_update.role
    # 如果传入权限则更新权限
    if member_update.permissions:
        member.permissions = member_update.permissions
    # 提交事务
    await db.commit()
    # 刷新对象
    await db.refresh(member)
    # 重新加载成员并预加载用户关系
    result = await db.execute(
        # 构造成员查询
        select(ProjectMember)
        # 预加载 user 关联
        .options(selectinload(ProjectMember.user))
        # 根据成员 ID 定位
        .where(ProjectMember.id == member.id)
    )
    # 返回更新后的成员
    return result.scalars().first()


@router.delete("/{project_id}/members/{member_id}")
async def remove_project_member(
    project_id: str,
    member_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    从项目中移除成员。

    处理流程：
    - 校验项目是否存在
    - 校验当前用户权限
    - 获取成员记录
    - 删除成员并提交
    """
    # 读取项目，确认项目是否存在
    project = await db.get(Project, project_id)
    # 若项目不存在则返回 404
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    # 校验当前用户是否为项目所有者或超级管理员
    if project.owner_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="权限不足")
    # 查询目标成员记录
    result = await db.execute(
        # 构造成员查询
        select(ProjectMember)
        # 同时匹配成员与项目
        .where(ProjectMember.id == member_id, ProjectMember.project_id == project_id)
    )
    # 获取成员对象
    member = result.scalars().first()
    # 若成员不存在则返回 404
    if not member:
        raise HTTPException(status_code=404, detail="成员不存在")
    # 删除成员记录
    await db.delete(member)
    # 提交事务
    await db.commit()
    # 返回删除结果
    return {"message": "成员已移除"}





