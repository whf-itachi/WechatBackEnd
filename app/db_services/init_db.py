"""
初始化数据库表结构(首次部署应用时创建表结构、开发阶段重置测试数据库)
生产环境应使用Alembic迁移工具替代直接执行init_db.py
"""

from sqlmodel import SQLModel
from database import engine

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

if __name__ == "__main__":
    create_db_and_tables()