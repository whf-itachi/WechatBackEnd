"""幂等建表 / 升级脚本：出差记录表

用法（在 WechatBackEnd 目录、激活虚拟环境后）：
    python scripts/init_trip_table.py              # 新库直接建表；老库自动迁移
    python scripts/init_trip_table.py --dedupe     # 顺带清理"同一天多条"的历史重复

规则：一天一条 —— 唯一键 (user_id, trip_date)。
如果库里已经存在同一天多条的历史数据，默认**不删除任何数据**，只打印明细并跳过
建唯一索引（接口层仍会拦重复提交）；确认可以清理时加 --dedupe，
脚本会按「每组保留 id 最小的一条」删除多余的，再建唯一索引。
重复执行安全。
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.db_services.database import engine  # noqa: E402

DEDUPE = "--dedupe" in sys.argv

DDL = """
CREATE TABLE IF NOT EXISTS `trip_record` (
  `id`          INT           NOT NULL AUTO_INCREMENT,
  `user_id`     INT           NOT NULL,
  `trip_date`   DATE          NOT NULL,
  `trip_reason` VARCHAR(1000) NOT NULL,
  `cycle_key`   VARCHAR(7)    NOT NULL,
  `create_at`   DATETIME      NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_trip_user_date` (`user_id`, `trip_date`),
  KEY `ix_trip_record_trip_date` (`trip_date`),
  KEY `ix_trip_cycle_key` (`cycle_key`),
  CONSTRAINT `trip_record_user_fk` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='出差记录表'
"""


async def main() -> None:
    async with engine.begin() as conn:
        await conn.execute(text(DDL))

        # ---------- 1. 列迁移 ----------
        cols = (
            await conn.execute(
                text(
                    "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'trip_record'"
                )
            )
        ).scalars().all()

        # 旧列 device_no → trip_reason（含长度放宽到 1000）
        if "device_no" in cols and "trip_reason" not in cols:
            await conn.execute(
                text(
                    "ALTER TABLE `trip_record` CHANGE COLUMN `device_no` `trip_reason` "
                    "VARCHAR(1000) NOT NULL COMMENT '出差原因/工作内容，自由文本'"
                )
            )
            print("已升级：device_no -> trip_reason")

        # 姓名不再落库：展示/导出时 join user 表取最新姓名
        if "user_name" in cols:
            await conn.execute(text("ALTER TABLE `trip_record` DROP COLUMN `user_name`"))
            print("已升级：删除 user_name 列（姓名改为 join user 表获取）")

        # ---------- 2. 一天一条：唯一索引 ----------
        indexes = (
            await conn.execute(
                text(
                    "SELECT DISTINCT INDEX_NAME FROM information_schema.STATISTICS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'trip_record'"
                )
            )
        ).scalars().all()

        if "uq_trip_user_date" not in indexes:
            # 建唯一键前先看有没有「同一天多条」的历史数据
            dups = (
                await conn.execute(
                    text(
                        "SELECT user_id, trip_date, COUNT(*) AS c, "
                        "GROUP_CONCAT(id ORDER BY id) AS ids "
                        "FROM `trip_record` GROUP BY user_id, trip_date HAVING c > 1"
                    )
                )
            ).all()

            if dups and not DEDUPE:
                print("\n！存在同一天多条的历史记录，已跳过创建唯一索引（未删除任何数据）：")
                for user_id, trip_date, cnt, ids in dups:
                    print(f"  user_id={user_id}  {trip_date}  {cnt} 条  id={ids}")
                print(
                    "  确认可以清理后重跑：python scripts/init_trip_table.py --dedupe\n"
                    "  （保留每组 id 最小的一条，其余删除）\n"
                    "  注意：不建唯一索引时，防重复只靠接口层校验，并发下仍可能写重。"
                )
            else:
                if dups:
                    # 每组保留 id 最小的一条（不用窗口函数，兼容 MySQL 5.7/8）
                    await conn.execute(
                        text(
                            "DELETE t1 FROM `trip_record` t1 "
                            "JOIN `trip_record` t2 "
                            "  ON t1.user_id = t2.user_id "
                            " AND t1.trip_date = t2.trip_date "
                            " AND t1.id > t2.id"
                        )
                    )
                    removed = sum(cnt - 1 for _, _, cnt, _ in dups)
                    print(f"已清理历史重复记录 {removed} 条（每组保留 id 最小的一条）")

                await conn.execute(
                    text(
                        "ALTER TABLE `trip_record` "
                        "ADD UNIQUE KEY `uq_trip_user_date` (`user_id`, `trip_date`)"
                    )
                )
                print("已升级：新增唯一索引 uq_trip_user_date（一天一条）")

        # 唯一索引建好后，停用时期的普通索引就冗余了；外键此时借用唯一索引，
        # 可以安全删除（顺序不能反，否则报 1553）
        indexes = (
            await conn.execute(
                text(
                    "SELECT DISTINCT INDEX_NAME FROM information_schema.STATISTICS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'trip_record'"
                )
            )
        ).scalars().all()
        if "ix_trip_user_date" in indexes and "uq_trip_user_date" in indexes:
            await conn.execute(text("ALTER TABLE `trip_record` DROP INDEX `ix_trip_user_date`"))
            print("已升级：移除冗余普通索引 ix_trip_user_date（由唯一索引覆盖）")

        # ---------- 3. 外键规则 ----------
        # 用户删除已改为软删除（is_active=False），外键同步收紧为 RESTRICT：
        # 万一有人绕过接口物理删用户，直接报错而不是静默抹掉历史账目
        rule = (
            await conn.execute(
                text(
                    "SELECT DELETE_RULE FROM information_schema.REFERENTIAL_CONSTRAINTS "
                    "WHERE CONSTRAINT_SCHEMA = DATABASE() AND TABLE_NAME = 'trip_record' "
                    "AND CONSTRAINT_NAME = 'trip_record_user_fk'"
                )
            )
        ).scalar()
        if rule and rule.upper() == "CASCADE":
            await conn.execute(text("ALTER TABLE `trip_record` DROP FOREIGN KEY `trip_record_user_fk`"))
            await conn.execute(
                text(
                    "ALTER TABLE `trip_record` ADD CONSTRAINT `trip_record_user_fk` "
                    "FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE RESTRICT"
                )
            )
            print("已升级：外键 ON DELETE CASCADE -> RESTRICT（防止误删用户连带删记录）")

    await engine.dispose()
    print("trip_record 已就绪")


if __name__ == "__main__":
    asyncio.run(main())
