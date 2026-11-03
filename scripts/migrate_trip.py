"""出差记录表迁移脚本：建表 / 老表升级（二合一，幂等）

为什么需要它：
  `app/models/trip.py` 只是 ORM 映射，SQLModel 不会在运行期建表；本项目里既没有
  `create_all`，也没接 Alembic（`alembic/versions` 为空）。也就是说**表结构的唯一来源
  就是这个脚本**——新环境（本机、测试、客户服务器）重放一次即可,服务启动不依赖它。

用法（在 WechatBackEnd 目录执行，用项目自己的 python）：
    python scripts/migrate_trip.py --print-sql     # 只打印 v2 建表 DDL（给 DBA 或存档用）
    python scripts/migrate_trip.py --dry-run       # 只体检，不改任何东西（上生产先跑这个）
    python scripts/migrate_trip.py                 # 执行：空库建 v2；老库原地升到 v2
    python scripts/migrate_trip.py --move-to-task  # 超长 project 原文先搬进 task 再截断（推荐）
    python scripts/migrate_trip.py --truncate      # 超长 project 直接截断（会丢字，慎用）
    python scripts/migrate_trip.py --dedupe        # 清理"同一天多条"历史重复，再建唯一索引

表结构版本：
    v0  device_no              （更早的版本）
    v1  trip_reason(1000)      （自由文本的"出差原因"）
    v2  工作日报，对齐 `Daily Report in China all_2026.xlsx` 的 Working Overview：
        project(50) / task(500) / customer(100) / worktime_begin / worktime_end /
        total_worktime / remark(500) / update_at

数据安全：
  1. `project` 从 VARCHAR(1000) 收敛到 50，历史自由文本很可能超长。默认**不删除、
     不截断任何内容**，只打印超长明细并跳过收敛（列宽保持 1000）；接口层仍按 50 校验。
     确认处理方式后再加 --move-to-task 或 --truncate 重跑。
  2. 唯一索引（一天一条）建之前会检查重复数据，默认只报告并跳过建索引，不删数据；
     确认可清理时加 --dedupe（每组保留 id 最小的一条）。

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
TRUNCATE = "--truncate" in sys.argv
MOVE_TO_TASK = "--move-to-task" in sys.argv
DEDUPE = "--dedupe" in sys.argv

PROJECT_MAX_LEN = 50

# 历史列名，按新旧顺序：device_no → trip_reason → project
LEGACY_NAMES = ["device_no", "trip_reason"]

# 新增列：顺序紧跟在 project 之后，导出时列序与 Excel 一致，排查数据也更直观
NEW_COLUMNS = [
    ("task", "VARCHAR(500) NULL COMMENT '当天工作具体内容（Task）'", "project"),
    ("customer", "VARCHAR(100) NULL COMMENT '客户名称（Customer）'", "task"),
    ("worktime_begin", "TIME NULL COMMENT '当天工作开始时间'", "customer"),
    ("worktime_end", "TIME NULL COMMENT '当天工作结束时间'", "worktime_begin"),
    ("total_worktime", "DECIMAL(5,2) NULL COMMENT '当天工作总时长（小时，(end-begin)*24）'", "worktime_end"),
    ("remark", "VARCHAR(500) NULL COMMENT '当天备注（备注列）'", "total_worktime"),
    ("update_at", "DATETIME NULL COMMENT '最后修改时间（截止前允许多次修改）'", "remark"),
]

# v2 完整建表语句。空库直接执行；老库不要指望它升级（CREATE TABLE IF NOT EXISTS 遇到已存在的表
# 会整条跳过），老库走下面的列迁移逻辑。
DDL = """
CREATE TABLE IF NOT EXISTS `trip_record` (
  `id`              INT           NOT NULL AUTO_INCREMENT,
  `user_id`         INT           NOT NULL,
  `trip_date`       DATE          NOT NULL,
  `project`         VARCHAR(50)   NOT NULL COMMENT '项目名称（对应 Project 列）',
  `task`            VARCHAR(500)  NULL COMMENT '当天工作具体内容（Task）',
  `customer`        VARCHAR(100)  NULL COMMENT '客户名称（Customer）',
  `worktime_begin`  TIME          NULL COMMENT '当天工作开始时间',
  `worktime_end`    TIME          NULL COMMENT '当天工作结束时间',
  `total_worktime`  DECIMAL(5,2)  NULL COMMENT '当天工作总时长（小时，(end-begin)*24）',
  `remark`          VARCHAR(500)  NULL COMMENT '当天备注（备注列）',
  `cycle_key`       VARCHAR(7)    NOT NULL,
  `create_at`       DATETIME      NOT NULL,
  `update_at`       DATETIME      NULL COMMENT '最后修改时间（截止前允许多次修改）',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_trip_user_date` (`user_id`, `trip_date`),
  KEY `ix_trip_record_trip_date` (`trip_date`),
  KEY `ix_trip_cycle_key` (`cycle_key`),
  CONSTRAINT `trip_record_user_fk` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='出差记录表（工作日报）'
"""


async def _columns(conn) -> list:
    return (
        await conn.execute(
            text(
                "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'trip_record' "
                "ORDER BY ORDINAL_POSITION"
            )
        )
    ).scalars().all()


async def _indexes(conn) -> list:
    return (
        await conn.execute(
            text(
                "SELECT DISTINCT INDEX_NAME FROM information_schema.STATISTICS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'trip_record'"
            )
        )
    ).scalars().all()


async def _table_exists(conn) -> bool:
    return bool(
        (
            await conn.execute(
                text(
                    "SELECT COUNT(*) FROM information_schema.TABLES "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'trip_record'"
                )
            )
        ).scalar()
    )


async def _inspect(conn, cols: list) -> bool:
    """体检 + 计划（只读）。返回 False 表示表结构异常，后续不应继续动它。"""
    total = (await conn.execute(text("SELECT COUNT(*) FROM `trip_record`"))).scalar()
    print(f"表 trip_record：{total} 条记录")
    print("现有列：" + ", ".join(cols))

    legacy = [c for c in LEGACY_NAMES if c in cols]
    if len(legacy) > 1 or ("project" in cols and legacy):
        both = legacy + (["project"] if "project" in cols else [])
        print(f"！同时存在多列 {both}，请人工确认数据归属后再跑")
        return False

    if legacy:
        src = legacy[0]
        print(f"识别为旧结构：{src} → 将重命名为 project（先保留 VARCHAR(1000)）")
    elif "project" in cols:
        src = "project"
        print("project 列已存在")
    else:
        print("！既没有 device_no / trip_reason，也没有 project，表结构异常，请人工检查")
        return False

    missing = [n for n, _, _ in NEW_COLUMNS if n not in cols]
    print("待新增列：" + (", ".join(missing) if missing else "无（都齐了）"))

    max_len = (
        await conn.execute(text(f"SELECT COALESCE(MAX(CHAR_LENGTH(`{src}`)), 0) FROM `trip_record`"))
    ).scalar() or 0
    print(f"{src} 最长 {max_len} 字符（上限 {PROJECT_MAX_LEN}）")

    if max_len > PROJECT_MAX_LEN:
        overlong = (
            await conn.execute(
                text(
                    f"SELECT id, user_id, trip_date, CHAR_LENGTH(`{src}`) AS len, LEFT(`{src}`, 60) AS preview "
                    f"FROM `trip_record` WHERE CHAR_LENGTH(`{src}`) > :m ORDER BY id"
                ),
                {"m": PROJECT_MAX_LEN},
            )
        ).all()
        print(f"\n！有 {len(overlong)} 条历史记录超过 {PROJECT_MAX_LEN} 字符，明细如下：")
        for rid, uid, tdate, length, preview in overlong:
            print(f"  id={rid} user_id={uid} {tdate} {length}字  {preview!r}")
        if MOVE_TO_TASK:
            print("  本次将执行：原文整体搬到 task（已有内容追加其后），再把 project 截到 50 字")
        elif TRUNCATE:
            print("  本次将执行：project 直接截断到 50 字（原内容丢弃）")
        else:
            print(
                "  本次**不动**这些数据，project 列宽保持 VARCHAR(1000)；\n"
                "  确认处理方式后重跑：\n"
                "    --move-to-task  把超长原文搬到 task 再截断（推荐，不丢内容）\n"
                "    --truncate      直接截断（会丢字）"
            )
    print()
    return True


async def _ensure_unique_index(conn) -> None:
    """一天一条：唯一索引 (user_id, trip_date)。

    库里若已有同一天多条的历史数据，默认只报告不删；加 --dedupe 才清理。
    """
    indexes = await _indexes(conn)
    if "uq_trip_user_date" in indexes:
        return

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
            "  确认可以清理后重跑：python scripts/migrate_trip.py --dedupe\n"
            "  （保留每组 id 最小的一条，其余删除）\n"
            "  注意：不建唯一索引时，防重复只靠接口层校验，并发下仍可能写重。"
        )
        return

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
        text("ALTER TABLE `trip_record` ADD UNIQUE KEY `uq_trip_user_date` (`user_id`, `trip_date`)")
    )
    print("已升级：新增唯一索引 uq_trip_user_date（一天一条）")


async def _drop_redundant_index(conn) -> None:
    """唯一索引建好后，停用时期的普通索引就冗余了；外键此时借用唯一索引，可安全删除
    （顺序不能反，否则报 1553）"""
    indexes = await _indexes(conn)
    if "ix_trip_user_date" in indexes and "uq_trip_user_date" in indexes:
        await conn.execute(text("ALTER TABLE `trip_record` DROP INDEX `ix_trip_user_date`"))
        print("已升级：移除冗余普通索引 ix_trip_user_date（由唯一索引覆盖）")


async def _ensure_fk_restrict(conn) -> None:
    """用户删除已改为软删除（is_active=False），外键同步收紧为 RESTRICT：
    万一有人绕过接口物理删用户，直接报错而不是静默抹掉历史账目"""
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
        print("表 trip_record 不存在")
        print("本次将执行：按 v2 结构建表（含唯一索引 uq_trip_user_date、外键 RESTRICT）")
        if DRY_RUN:
            print("\n[dry-run] 以上只是体检，未做任何修改。确认无误后去掉 --dry-run 重跑。")
            await engine.dispose()
            return
    else:
        async with engine.connect() as conn:
            if not await _inspect(conn, cols):
                print("已中止，未做任何修改。")
                await engine.dispose()
                return
        if DRY_RUN:
            print("[dry-run] 以上只是体检，未做任何修改。确认无误后去掉 --dry-run 重跑。")
            await engine.dispose()
            return

    # ---------- 2. 实际执行 ----------
    project_pending = False  # project 列宽未收敛（超长历史数据待确认）
    async with engine.begin() as conn:
        if not exists:
            await conn.execute(text(DDL))
            print("已创建：trip_record（v2 结构）")
            cols = await _columns(conn)
        else:
            # 2.1 历史列改名 → project
            legacy = [c for c in LEGACY_NAMES if c in cols]
            if legacy and "project" not in cols:
                src = legacy[0]
                # 先保持原宽度完成重命名，等确认怎么处理超长内容后再收敛到 50
                await conn.execute(
                    text(
                        f"ALTER TABLE `trip_record` CHANGE COLUMN `{src}` `project` "
                        "VARCHAR(1000) NOT NULL COMMENT '项目名称（原出差原因）'"
                    )
                )
                print(f"已升级：{src} -> project（先保留 VARCHAR(1000)，等确认后收敛到 50）")
                cols = await _columns(conn)

            # 2.2 姓名不再落库：展示/导出时 join user 表取最新姓名
            if "user_name" in cols:
                await conn.execute(text("ALTER TABLE `trip_record` DROP COLUMN `user_name`"))
                print("已升级：删除 user_name 列（姓名改为 join user 表获取）")
                cols = await _columns(conn)

            # 2.3 补齐新增列
            for name, ddl, after in NEW_COLUMNS:
                if name in cols:
                    continue
                await conn.execute(text(f"ALTER TABLE `trip_record` ADD COLUMN `{name}` {ddl} AFTER `{after}`"))
                print(f"已升级：新增列 {name}")
            cols = await _columns(conn)

            # 2.4 project 长度收敛到 50
            if "project" in cols:
                project_type = (
                    await conn.execute(
                        text(
                            "SELECT COLUMN_TYPE FROM information_schema.COLUMNS "
                            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'trip_record' "
                            "AND COLUMN_NAME = 'project'"
                        )
                    )
                ).scalar()
                max_len = (
                    await conn.execute(text("SELECT COALESCE(MAX(CHAR_LENGTH(`project`)), 0) FROM `trip_record`"))
                ).scalar() or 0

                shrunk = False
                if max_len > PROJECT_MAX_LEN:
                    if MOVE_TO_TASK:
                        # 原文整体搬进 task（已有 task 内容时追加在后面，不覆盖），再把 project 截到 50
                        await conn.execute(
                            text(
                                "UPDATE `trip_record` SET `task` = "
                                "CASE WHEN `task` IS NULL OR `task` = '' THEN `project` "
                                "ELSE CONCAT(`project`, '\\n', `task`) END "
                                "WHERE CHAR_LENGTH(`project`) > :m"
                            ),
                            {"m": PROJECT_MAX_LEN},
                        )
                        await conn.execute(
                            text(
                                "UPDATE `trip_record` SET `project` = LEFT(`project`, :m) "
                                "WHERE CHAR_LENGTH(`project`) > :m"
                            ),
                            {"m": PROJECT_MAX_LEN},
                        )
                        print(f"已处理：超长原文迁移到 task，project 截取前 {PROJECT_MAX_LEN} 字符")
                        shrunk = True
                    elif TRUNCATE:
                        await conn.execute(
                            text(
                                "UPDATE `trip_record` SET `project` = LEFT(`project`, :m) "
                                "WHERE CHAR_LENGTH(`project`) > :m"
                            ),
                            {"m": PROJECT_MAX_LEN},
                        )
                        print(f"已处理：project 直接截取前 {PROJECT_MAX_LEN} 字符（原内容已丢弃）")
                        shrunk = True
                    else:
                        print(
                            f"  未做任何修改，project 仍为 {project_type}。\n"
                            "  确认处理方式后重跑：\n"
                            "    --move-to-task  把超长原文搬到 task 再截断（推荐，不丢内容）\n"
                            "    --truncate      直接截断（会丢字）\n"
                            "  注意：列宽未收敛前，接口仍只接受 50 字符以内的新数据。"
                        )
                        project_pending = True
                else:
                    shrunk = True

                if shrunk and not project_type.startswith("varchar(50)"):
                    await conn.execute(
                        text(
                            "ALTER TABLE `trip_record` MODIFY COLUMN `project` "
                            "VARCHAR(50) NOT NULL COMMENT '项目名称（对应 Project 列）'"
                        )
                    )
                    print("已升级：project 收敛为 VARCHAR(50) NOT NULL")

        # 2.5 回填总时长：只处理两端都有时间但 total_worktime 为空的记录；跨零点补 24 小时，
        #     与接口里的 calc_total_worktime 完全同一口径
        result = await conn.execute(
            text(
                "UPDATE `trip_record` SET `total_worktime` = ROUND(("
                "  CASE WHEN `worktime_end` >= `worktime_begin` "
                "       THEN TIMESTAMPDIFF(MINUTE, `worktime_begin`, `worktime_end`) "
                "       ELSE TIMESTAMPDIFF(MINUTE, `worktime_begin`, `worktime_end`) + 1440 END"
                ") / 60, 2) "
                "WHERE `worktime_begin` IS NOT NULL AND `worktime_end` IS NOT NULL "
                "  AND `total_worktime` IS NULL"
            )
        )
        if result.rowcount:
            print(f"已回填 total_worktime {result.rowcount} 条")

        # 2.6 约束与索引
        await _ensure_unique_index(conn)
        await _drop_redundant_index(conn)
        await _ensure_fk_restrict(conn)

    # ---------- 3. 收尾 ----------
    async with engine.connect() as conn:
        cols = await _columns(conn)
        print("\ntrip_record 当前列：" + ", ".join(cols))
    await engine.dispose()
    if project_pending:
        print("trip_record 结构已就绪（v2），但 project 列宽尚未收敛：先确认超长历史数据怎么处理，再重跑。")
    else:
        print("trip_record 已就绪（v2）")


if __name__ == "__main__":
    asyncio.run(main())
