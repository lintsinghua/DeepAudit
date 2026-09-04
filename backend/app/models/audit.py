"""
模块说明：数据模型定义：audit。
"""

import uuid
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Text, Float
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.base import Base


class AuditTask(Base):
    __tablename__ = "audit_tasks"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    created_by = Column(String, ForeignKey("users.id"), nullable=False)
    
    task_type = Column(String, nullable=False)
    status = Column(String, default="pending", index=True)
    branch_name = Column(String, nullable=True)
    
    exclude_patterns = Column(Text, default="[]")
    scan_config = Column(Text, default="{}")
    
    # Stats
    total_files = Column(Integer, default=0)
    scanned_files = Column(Integer, default=0)
    total_lines = Column(Integer, default=0)
    issues_count = Column(Integer, default=0)
    quality_score = Column(Float, default=0.0)
    
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    project = relationship("Project", back_populates="tasks")
    creator = relationship("User", foreign_keys=[created_by])
    issues = relationship("AuditIssue", back_populates="task", cascade="all, delete-orphan")


class AuditIssue(Base):
    __tablename__ = "audit_issues"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = Column(String, ForeignKey("audit_tasks.id"), nullable=False)
    
    file_path = Column(String, nullable=False)
    line_number = Column(Integer, nullable=True)
    column_number = Column(Integer, nullable=True)
    issue_type = Column(String, nullable=False)
    severity = Column(String, nullable=False)  # critical, high, medium, low
    
    # 问题信息
    title = Column(String, nullable=True)  # 问题标题
    message = Column(Text, nullable=True)  # 兼容旧字段，同title
    description = Column(Text, nullable=True)  # 详细描述
    suggestion = Column(Text, nullable=True)  # 修复建议
    code_snippet = Column(Text, nullable=True)  # 问题代码片段
    ai_explanation = Column(Text, nullable=True)  # AI解释（JSON格式的xai字段）
    
    status = Column(String, default="open")  # open, resolved, false_positive
    resolved_by = Column(String, ForeignKey("users.id"), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    task = relationship("AuditTask", back_populates="issues")
    resolver = relationship("User", foreign_keys=[resolved_by])
