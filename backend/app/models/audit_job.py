"""Durable delivery and recovery metadata for audit execution."""
from sqlalchemy import Boolean, Column, DateTime, Integer, JSON, String, Text, Index
from sqlalchemy.sql import func
from app.db.base import Base


class AuditJob(Base):
    __tablename__ = "audit_jobs"
    id = Column(String(36), primary_key=True)  # Same id as the owning audit task.
    kind = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False, default="queued")
    payload = Column(JSON, nullable=False, default=dict)
    checkpoint = Column(JSON, nullable=False, default=dict)
    attempts = Column(Integer, nullable=False, default=0)
    cancel_requested = Column(Boolean, nullable=False, default=False)
    worker_id = Column(String(100), nullable=True)
    lease_until = Column(DateTime(timezone=True), nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (Index("ix_audit_jobs_delivery", "status", "lease_until", "created_at"),)
