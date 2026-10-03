"""
模块说明：数据库初始化与会话管理：base。
"""

from sqlalchemy.orm import as_declarative, declared_attr

@as_declarative()
class Base:
    id: str
    __name__: str

    # Generate __tablename__ automatically
    @declared_attr
    def __tablename__(cls) -> str:
        return cls.__name__.lower() + "s"






