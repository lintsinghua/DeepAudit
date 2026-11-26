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


# Schemas
class UserSchema(BaseModel):
    id: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    role: Optional[str] = None

    class Config:
        from_attributes = True


class ProjectMemberSchema(BaseModel):
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
    user_id: str
    role: str = "member"


class UpdateMemberRequest(BaseModel):
    role: Optional[str] = None
    permissions: Optional[str] = None


@router.get("/{project_id}/members", response_model=List[ProjectMemberSchema])
async def get_project_members(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    Get all members of a project.
    """
    # Verify project exists
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    if project.owner_id != current_user.id and not current_user.is_superuser:
        member_id = await db.scalar(select(ProjectMember.id).where(
            ProjectMember.project_id == project_id, ProjectMember.user_id == current_user.id
        ))
        if member_id is None:
            raise HTTPException(status_code=403, detail="无权查看项目成员")

    result = await db.execute(
        select(ProjectMember)
        .options(selectinload(ProjectMember.user))
        .where(ProjectMember.project_id == project_id)
        .order_by(ProjectMember.joined_at.desc())
    )
    return result.scalars().all()


@router.post("/{project_id}/members", response_model=ProjectMemberSchema)
async def add_project_member(
    project_id: str,
    member_in: AddMemberRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    Add a member to a project.
    """
    # Verify project exists
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    # Check if user is project owner or admin
    if project.owner_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="权限不足")
    
    # Check if user exists
    user = await db.get(User, member_in.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    # Check if already a member
    existing = await db.execute(
        select(ProjectMember)
        .where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == member_in.user_id
        )
    )
    if existing.scalars().first():
        raise HTTPException(status_code=400, detail="用户已是项目成员")
    
    # Create member
    member = ProjectMember(
        project_id=project_id,
        user_id=member_in.user_id,
        role=member_in.role,
        permissions="{}"
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    
    # Reload with user relationship
    result = await db.execute(
        select(ProjectMember)
        .options(selectinload(ProjectMember.user))
        .where(ProjectMember.id == member.id)
    )
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
    Update a project member's role or permissions.
    """
    # Verify project exists
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    # Check permissions
    if project.owner_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="权限不足")
    
    # Get member
    result = await db.execute(
        select(ProjectMember)
        .where(ProjectMember.id == member_id, ProjectMember.project_id == project_id)
    )
    member = result.scalars().first()
    if not member:
        raise HTTPException(status_code=404, detail="成员不存在")
    
    # Update fields
    if member_update.role:
        member.role = member_update.role
    if member_update.permissions:
        member.permissions = member_update.permissions
    
    await db.commit()
    await db.refresh(member)
    
    # Reload with user relationship
    result = await db.execute(
        select(ProjectMember)
        .options(selectinload(ProjectMember.user))
        .where(ProjectMember.id == member.id)
    )
    return result.scalars().first()


@router.delete("/{project_id}/members/{member_id}")
async def remove_project_member(
    project_id: str,
    member_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    Remove a member from a project.
    """
    # Verify project exists
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    # Check permissions
    if project.owner_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="权限不足")
    
    # Get member
    result = await db.execute(
        select(ProjectMember)
        .where(ProjectMember.id == member_id, ProjectMember.project_id == project_id)
    )
    member = result.scalars().first()
    if not member:
        raise HTTPException(status_code=404, detail="成员不存在")
    
    await db.delete(member)
    await db.commit()
    
    return {"message": "成员已移除"}






