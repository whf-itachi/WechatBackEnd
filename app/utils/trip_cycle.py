"""出差填报周期规则（单一事实来源，移动端/后台都必须调用这里的函数）

规则定义：
- 结算日为每月 25 日。周期窗口 = [上月 26 日, 本月 25 日]，结算月 = 本月（YYYY-MM）。
  例：结算月 2026-11 的窗口是 2026-10-26 ~ 2026-11-25。
  窗口起点取 26 日而非 25 日，保证一个窗口内只有一个 25 号（即本期截止日），
  相邻窗口首尾相接、不再在 25 号这个端点重叠。
- 「当前可填报周期」= 包含今天的那一个窗口：
  * 今天 > 25 日 → 结算月为下个月；
  * 今天 <= 25 日 → 结算月为今天所在月。
  25 号是结算日、仍算本月；26 号起才进入下一个周期，旧周期随之关闭、不能再补填。
- 周期内只允许填写 <= 今天的日期（不能填未来）。
- 归属统一按「25 号算本月、26 号算下月」判定：cycle_of() 与 cycle_by_key() 对同一天的
  窗口与归属完全一致，不存在边界日归到相邻月的分歧。记录写入时按所属周期打 cycle_key，
  后台按 cycle_key 归集，不重复计数。
"""

from datetime import date, datetime, timedelta, timezone

CN_TZ = timezone(timedelta(hours=8))  # 业务面向国内，固定 UTC+8，避免服务器时区差异
DEADLINE_DAY = 25


def now_cn() -> datetime:
    """当前北京时间（naive 之外带时区，便于与其他 UTC 字段比较）"""
    return datetime.now(CN_TZ)


def today_cn() -> date:
    return now_cn().date()


def to_cn(dt):
    """库里的 DATETIME 存的是 UTC 朴素时间，展示/导出前统一转成北京时间。

    MySQL DATETIME 不保留时区，读出来是 naive，直接 astimezone() 会当成服务器本地时间，
    在 UTC 部署的机器上会差 8 小时，所以这里显式补 UTC 时区再转换。
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(CN_TZ)


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    total = year * 12 + (month - 1) + delta
    return total // 12, total % 12 + 1


def _month_day(year: int, month: int, day: int) -> date:
    """构造日期，day 超出当月天数时收敛到月末（25 永远存在，这里只是防御性兜底）"""
    try:
        return date(year, month, day)
    except ValueError:
        return date(year, month, 28)


def cycle_of(day: date) -> tuple[date, date, str]:
    """给定日期，返回其所在填报窗口 (start, end, cycle_key)

    25 号算本月、26 号起算下月，与 cycle_by_key() 的窗口定义一致。
    """
    if day.day > DEADLINE_DAY:
        # 26 号起算下月：窗口起点 = 本月 26 日（不是 25 日，否则与上一期在 25 号重叠）
        start = date(day.year, day.month, DEADLINE_DAY + 1)
        y, m = _shift_month(day.year, day.month, 1)
        end = date(y, m, DEADLINE_DAY)
        key_y, key_m = y, m
    else:
        # 25 号及之前算本月：窗口起点 = 上月 26 日
        py, pm = _shift_month(day.year, day.month, -1)
        start = date(py, pm, DEADLINE_DAY + 1)
        end = date(day.year, day.month, DEADLINE_DAY)
        key_y, key_m = day.year, day.month
    return start, end, f"{key_y:04d}-{key_m:02d}"


def cycle_by_key(key: str) -> tuple[date, date, str]:
    """按结算月反查窗口，key 形如 2026-11 → (2026-10-26, 2026-11-25, '2026-11')"""
    parts = (key or "").split("-")
    if len(parts) != 2:
        raise ValueError("结算月格式应为 YYYY-MM")
    year, month = int(parts[0]), int(parts[1])
    if not (1 <= month <= 12):
        raise ValueError("结算月格式应为 YYYY-MM")
    py, pm = _shift_month(year, month, -1)
    return date(py, pm, DEADLINE_DAY + 1), date(year, month, DEADLINE_DAY), f"{year:04d}-{month:02d}"


def current_cycle() -> tuple[date, date, str]:
    return cycle_of(today_cn())


def recent_cycle_keys(count: int = 12) -> list[str]:
    """最近 count 个结算月（含当前），从新到旧，供后台下拉选择"""
    _, _, key = current_cycle()
    year, month = int(key[:4]), int(key[5:7])
    keys = []
    for i in range(count):
        y, m = _shift_month(year, month, -i)
        keys.append(f"{y:04d}-{m:02d}")
    return keys
