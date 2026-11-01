"""
模块说明：数据模型定义：analysis。
"""

import uuid
from sqlalchemy import Column, String, Integer, DateTime, Float, Text, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.base import Base

class InstantAnalysis(Base):
    __tablename__ = "instant_analyses"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=True) # Can be anonymous? Logic says usually logged in, but localDB allowed check.
    
    language = Column(String, nullable=False)
    code_content = Column(Text, default="") 
    analysis_result = Column(Text, default="{}")
    issues_count = Column(Integer, default=0)
    quality_score = Column(Float, default=0.0)
    analysis_time = Column(Float, default=0.0)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user = relationship("User", backref="instant_analyses")






