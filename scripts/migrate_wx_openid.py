"""用户表微信绑定字段迁移：加 wx_openid 列 + 唯一索引（幂等）

与 migrate_trip.py / migrate_expense.py 同一套约定：本项目没有 create_all、
也没有启用 Alembic（alembic/versions 为空），表结构变更由脚本重放完成。

用法（在 WechatBackEnd 目录，用项目自己的 python）：
    python scripts/migrate_wx_openid.py --print-sql   # 只打印 DDL，给 DBA 存档
    python scripts/migrate_wx_openid.py --dry-run     # 只体检，不改任何东西
    python scripts/migrate_wx_openid.py               # 执行迁移

双向唯一靠 MySQL 唯一索引保证：一个账号只有一个 openid，一个 openid 只属于一个账号；
NULL 表示该账号未绑定微信，MySQL 唯一索引允许多个 NULL，所以不影响历史账号。
重复执行安全，已到位的步骤会跳过。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.db_services.database import engine  # noqa: E402

DRY_RUN = "--dry-run" in sys.argv
PRINT_SQL = "--print-sql" in sys.argv

ADD_COLUMN_SQL = (
    "ALTER TABLE `user` ADD COLUMN `wx_openid` VARCHAR(64) NULL "
    "COMMENT '微信小程序 openid（双向唯一，NULL 表示未绑定）' AFTER `user_type`"
)
ADD_INDEX_SQL = "CREATE UNIQUE INDEX `uq_user_wx_openid` ON `user` (`wx_openid`)"


async def main():
    if PRINT_SQL:
        print(ADD_COLUMN_SQL + ";")
        print(ADD_INDEX_SQL + ";")
        return

    async with engine.begin() as conn:
        col = (
            await conn.execute(
                text(
                    "SELECT COUNT(*) FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'user' "
                    "AND COLUMN_NAME = 'wx_openid'"
                )
            )
        ).scalar()
        idx = (
            await conn.execute(
                text(
                    "SELECT COUNT(*) FROM information_schema.STATISTICS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'user' "
                    "AND INDEX_NAME = 'uq_user_wx_openid'"
                )
            )
        ).scalar()

        print(f"当前状态: wx_openid 列={'已存在' if col else '不存在'}, "
              f"uq_user_wx_openid 索引={'已存在' if idx else '不存在'}")

        if DRY_RUN:
            print("--dry-run：不做任何修改")
            return

        if not col:
            await conn.execute(text(ADD_COLUMN_SQL))
            print("已添加列 wx_openid VARCHAR(64) NULL")
        else:
            print("跳过：列已存在")

        if not idx:
            await conn.execute(text(ADD_INDEX_SQL))
            print("已创建唯一索引 uq_user_wx_openid")
        else:
            print("跳过：索引已存在")

        print("迁移完成")


if __name__ == "__main__":
    asyncio.run(main())
