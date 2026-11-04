"""出差费用表（expense_record）迁移脚本：建表 / 补列（幂等）

为什么需要它：
  `app/models/expense.py` 只是 ORM 映射，SQLModel 不会在运行期建表；本项目既没有
  `create_all`，也没接 Alembic（`alembic/versions` 为空）。**表结构的唯一来源就是脚本**
  ——新环境重放一次即可，服务启动不依赖它。

用法（在 WechatBackEnd 目录执行，用项目自己的 python）：
    python scripts/migrate_expense.py --print-sql   # 只打印建表 DDL（给 DBA 或存档用）
    python scripts/migrate_expense.py --dry-run     # 只体检，不改任何东西（上生产先跑这个）
    python scripts/migrate_expense.py               # 执行：空库建表；已存在则只补缺失列

与 trip_record 的差别：
  - 没有 (user_id, expense_date) 唯一键 —— 同一天可以有多张发票；
  - 多一列 expense_date_end 表示「一张票跨多天」，单日票为 NULL。

幂等：重复执行安全，已到位的步骤全部跳过，已有列和数据不会被改动。
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.db_services.database import engine  # noqa: E402

DRY_RUN = "--dry-run" in sys.argv
PRINT_SQL = "--print-sql" in sys.argv

TABLE = "expense_record"

# 建表语句（v1）。表已存在时 CREATE TABLE IF NOT EXISTS 会整条跳过，老环境走补列逻辑。
DDL = """
CREATE TABLE IF NOT EXISTS `expense_record` (
  `id`               INT           NOT NULL AUTO_INCREMENT,
  `user_id`          INT           NOT NULL COMMENT '填写人 id',
  `expense_date`     DATE          NOT NULL COMMENT '发票产生日期（对应 Date 列）；跨天费用为区间起始日',
  `expense_date_end` DATE          NULL COMMENT '跨天费用的区间结束日；单日发票为 NULL',
  `project`          VARCHAR(50)   NULL COMMENT '项目（对应 Project 列，可空）',
  `reason`           VARCHAR(20)   NOT NULL COMMENT '报销种类（对应 Reason 列，固定选项）',
  `reason_detail`    VARCHAR(100)  NULL COMMENT '劳保用品/工具/其他的开放明细',
  `expense`          DECIMAL(10,2) NOT NULL COMMENT '开支金额（对应 Expense 列）',
  `explanation`      VARCHAR(500)  NULL COMMENT '该笔消费的注解（对应 Explanation 列）',
  `cycle_key`        VARCHAR(7)    NOT NULL COMMENT '归属结算月 YYYY-MM',
  `create_at`        DATETIME      NOT NULL COMMENT '提交时间',
  `update_at`        DATETIME      NULL COMMENT '最后修改时间',
  PRIMARY KEY (`id`),
  KEY `ix_expense_user_date` (`user_id`, `expense_date`),
  KEY `ix_expense_date` (`expense_date`),
  KEY `ix_expense_cycle_key` (`cycle_key`),
  CONSTRAINT `expense_record_user_fk` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='出差费用报销记录表'
"""

# 后续加列时在这里追加（name, ddl, after）；建表语句与这里保持同步
NEW_COLUMNS = [
    ("expense_date_end", "DATE NULL COMMENT '跨天费用的区间结束日'", "expense_date"),
    ("project", "VARCHAR(50) NULL COMMENT '项目'", "expense_date_end"),
    ("reason", "VARCHAR(20) NOT NULL DEFAULT '其他' COMMENT '报销种类'", "project"),
    ("reason_detail", "VARCHAR(100) NULL COMMENT '劳保用品/工具/其他的明细'", "reason"),
    ("expense", "DECIMAL(10,2) NOT NULL DEFAULT 0 COMMENT '开支金额'", "reason_detail"),
    ("explanation", "VARCHAR(500) NULL COMMENT '该笔消费的注解'", "expense"),
    ("cycle_key", "VARCHAR(7) NOT NULL DEFAULT '' COMMENT '归属结算月'", "explanation"),
    ("create_at", "DATETIME NULL COMMENT '提交时间'", "cycle_key"),
    ("update_at", "DATETIME NULL COMMENT '最后修改时间'", "create_at"),
]


async def _table_exists(conn) -> bool:
    return bool(
        (
            await conn.execute(
                text(
                    "SELECT COUNT(*) FROM information_schema.TABLES "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t"
                ),
                {"t": TABLE},
            )
        ).scalar()
    )


async def _columns(conn) -> list:
    return (
        await conn.execute(
            text(
                "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t ORDER BY ORDINAL_POSITION"
            ),
            {"t": TABLE},
        )
    ).scalars().all()


async def _indexes(conn) -> list:
    return (
        await conn.execute(
            text(
                "SELECT DISTINCT INDEX_NAME FROM information_schema.STATISTICS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t"
            ),
            {"t": TABLE},
        )
    ).scalars().all()


async def main() -> None:
    # ---------- 0. 只打印 DDL，不连库 ----------
    if PRINT_SQL:
        print(DDL.strip())
        return

    # ---------- 1. 体检（只读） ----------
    async with engine.connect() as conn:
        exists = await _table_exists(conn)
        cols = await _columns(conn) if exists else []

    if not exists:
        print(f"表 {TABLE} 不存在")
        print("本次将执行：按 v1 结构建表（含 3 个索引、外键 ON DELETE RESTRICT）")
    else:
        total = 0
        async with engine.connect() as conn:
            total = (await conn.execute(text(f"SELECT COUNT(*) FROM `{TABLE}`"))).scalar()
        missing = [n for n, _, _ in NEW_COLUMNS if n not in cols]
        print(f"表 {TABLE}：{total} 条记录")
        print("现有列：" + ", ".join(cols))
        print("待新增列：" + (", ".join(missing) if missing else "无（都齐了）"))

    if DRY_RUN:
        print("\n[dry-run] 以上只是体检，未做任何修改。确认无误后去掉 --dry-run 重跑。")
        await engine.dispose()
        return

    # ---------- 2. 实际执行 ----------
    async with engine.begin() as conn:
        if not exists:
            await conn.execute(text(DDL))
            print(f"已创建：{TABLE}（v1 结构）")
        else:
            cols = await _columns(conn)
            for name, ddl, after in NEW_COLUMNS:
                if name in cols:
                    continue
                await conn.execute(
                    text(f"ALTER TABLE `{TABLE}` ADD COLUMN `{name}` {ddl} AFTER `{after}`")
                )
                print(f"已升级：新增列 {name}")
            cols = await _columns(conn)

            indexes = await _indexes(conn)
            wanted = {
                "ix_expense_user_date": "(`user_id`, `expense_date`)",
                "ix_expense_date": "(`expense_date`)",
                "ix_expense_cycle_key": "(`cycle_key`)",
            }
            for idx, cols_ddl in wanted.items():
                if idx in indexes:
                    continue
                await conn.execute(
                    text(f"ALTER TABLE `{TABLE}` ADD INDEX `{idx}` {cols_ddl}")
                )
                print(f"已升级：新增索引 {idx}")

    # ---------- 3. 收尾 ----------
    async with engine.connect() as conn:
        cols = await _columns(conn)
        print(f"\n{TABLE} 当前列：" + ", ".join(cols))
    await engine.dispose()
    print(f"{TABLE} 已就绪（v1）")


if __name__ == "__main__":
    asyncio.run(main())
