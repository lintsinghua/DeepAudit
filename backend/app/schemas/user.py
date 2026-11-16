"""
模块说明：数据校验与序列化模型：user。
"""

from typing import Optional, List
from pydantic import BaseModel, EmailStr

class UserBase(BaseModel):
    email: Optional[EmailStr] = None
    is_active: Optional[bool] = True
    is_superuser: bool = False
    full_name: Optional[str] = None
    
    # Profile fields
    phone: Optional[str] = None
    avatar_url: Optional[str] = None
    role: str = "member"
    github_username: Optional[str] = None
    gitlab_username: Optional[str] = None

class UserCreate(UserBase):
    email: EmailStr
    password: str
    full_name: str

class UserUpdate(UserBase):
    password: Optional[str] = None

class UserInDBBase(UserBase):
    id: str
    created_at: Optional[object] = None # Datetime
    updated_at: Optional[object] = None

    class Config:
        from_attributes = True

class User(UserInDBBase):
    pass

class UserListResponse(BaseModel):
    users: List[User]
    total: int
    skip: int
    limit: int






