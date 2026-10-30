-- 出差记录表（MySQL 8）
-- 规则：一天一条 —— 唯一键 (user_id, trip_date)
-- 新库：直接执行本文件；老库（已有 trip_record 但结构不同）请改用
--       python scripts/init_trip_table.py  它会自动做列改名、索引调整与删列

CREATE TABLE IF NOT EXISTS `trip_record` (
  `id`          INT           NOT NULL AUTO_INCREMENT,
  `user_id`     INT           NOT NULL COMMENT '填写人（只填自己的，取登录态）',
  `trip_date`   DATE          NOT NULL COMMENT '出差日期：用户在日历上点选的那一天',
  `trip_reason` VARCHAR(1000) NOT NULL COMMENT '出差原因/工作内容，自由文本',
  `cycle_key`   VARCHAR(7)    NOT NULL COMMENT '归属结算月 YYYY-MM（封账快照）',
  `create_at`   DATETIME      NOT NULL COMMENT '提交时间(UTC)，仅审计用途',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_trip_user_date` (`user_id`, `trip_date`),
  KEY `ix_trip_record_trip_date` (`trip_date`),
  KEY `ix_trip_cycle_key` (`cycle_key`),
  CONSTRAINT `trip_record_user_fk` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='出差记录表';

-- 说明：
-- 1. 姓名不落库，展示/导出时 join `user` 表取最新姓名。
-- 2. 用户在后台执行「删除」走的是软删除（is_active=False），不会物理删行；
--    这里用 ON DELETE RESTRICT 作为兜底：将来若有人绕过接口物理删用户，会直接报错，
--    而不是静默级联删掉该员工的历史出差记录。
-- 3. 一天一条由唯一键 uq_trip_user_date 保证；接口层也会先查重并返回 409，
--    唯一键负责拦住并发重复提交。

-- ---------- 老表升级（如果之前建过允许"一天多条"的表） ----------
-- 先确认没有重复数据，否则唯一索引建不上：
-- SELECT user_id, trip_date, COUNT(*) c FROM `trip_record`
--   GROUP BY user_id, trip_date HAVING c > 1;
-- 确认可以清理后（每组保留 id 最小的一条）：
-- DELETE t1 FROM `trip_record` t1 JOIN `trip_record` t2
--   ON t1.user_id = t2.user_id AND t1.trip_date = t2.trip_date AND t1.id > t2.id;
--
-- ALTER TABLE `trip_record` ADD UNIQUE KEY `uq_trip_user_date` (`user_id`, `trip_date`);
-- ALTER TABLE `trip_record` DROP INDEX `ix_trip_user_date`;   -- 必须在唯一索引建好之后删，否则报 1553
