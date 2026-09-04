"""
模块说明：数据模型定义：project。
"""

import uuid
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.base import Base

class Project(Base):
    __tablename__ = "projects"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, index=True, nullable=False)
    description = Column(Text, nullable=True)
    
    # 项目来源类型: 'repository' (远程仓库) 或 'zip' (ZIP上传)
    source_type = Column(String(20), default="repository", nullable=False)
    
    # 仓库相关字段 (仅 source_type='repository' 时使用)
    repository_url = Column(String, nullable=True)
    repository_type = Column(String, default="other")  # github, gitlab, gitea, other
    default_branch = Column(String, default="main")
    
    programming_languages = Column(Text, default="[]")  # Stored as JSON string
    
    owner_id = Column(String, ForeignKey("users.id"), nullable=False)
    is_active = Column(Boolean(), default=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    owner = relationship("User", backref="projects")
    members = relationship("ProjectMember", back_populates="project", cascade="all, delete-orphan")
    tasks = relationship("AuditTask", back_populates="project", cascade="all, delete-orphan")
    agent_tasks = relationship("AgentTask", back_populates="project", cascade="all, delete-orphan")

class ProjectMember(Base):
    __tablename__ = "project_members"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    role = Column(String, default="member")
    permissions = Column(Text, default="{}")
    
    joined_at = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    project = relationship("Project", back_populates="members")
    user = relationship("User", backref="project_memberships")



