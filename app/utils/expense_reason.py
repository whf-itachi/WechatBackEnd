"""报销种类字典（唯一事实来源）

报销种类是**固定选项、不允许自由填写**：前端下拉、后台筛选、导出文案、接口校验
全部读这里的定义，任何一处新增种类只需改本文件。

分两层：「类别」用于下拉分组与后台筛选，「具体项」才是真正落到 `expense_record.reason`
的值（例如「出租车」）。劳保用品 / 工具 / 其他 三类的明细不在选项里穷举，改由用户在下拉后
填一个开放字段 `reason_detail`，导出时拼成「劳保用品-安全帽」这样的单行文本。
"""

from typing import Optional

# 明细必填的三类：只写「工具」「其他」对财务没有信息量，必须补一句具体买了什么 / 花了什么
DETAIL_REQUIRED = ("劳保用品", "工具", "其他")

# 顺序即下拉展示顺序，不要按字母重排
REASON_GROUPS = [
    {
        "group": "交通工具",
        "items": ["出租车", "滴滴车", "公交车", "大巴车", "地铁", "火车", "飞机"],
        "detail_required": False,
    },
    {
        "group": "其他费用",
        "items": ["租车费", "汽油费", "过路费", "住宿费", "快递费", "焊工"],
        "detail_required": False,
    },
    {
        "group": "业务招待费",
        "items": ["客户礼物", "餐饮费"],
        "detail_required": False,
    },
    {
        "group": "劳保用品",
        "items": ["劳保用品"],
        "detail_required": True,
    },
    {
        "group": "工具",
        "items": ["工具"],
        "detail_required": True,
    },
    {
        "group": "其他",
        "items": ["其他"],
        "detail_required": True,
    },
]

# 扁平化的全部可选值，用于接口校验（顺序与分组一致）
ALL_REASONS = [item for g in REASON_GROUPS for item in g["items"]]

# 值 → 类别，后台按类别筛选时反查用
REASON_TO_GROUP = {item: g["group"] for g in REASON_GROUPS for item in g["items"]}


def is_valid_reason(reason: Optional[str]) -> bool:
    return reason in ALL_REASONS


def needs_detail(reason: Optional[str]) -> bool:
    return reason in DETAIL_REQUIRED


def reason_text(reason: Optional[str], detail: Optional[str] = None) -> str:
    """导出 / 页面展示用的完整报销种类文本。

    有明细 → 「工具-22mm 套筒」（对应 Expenses 表里 Reason 列直接写细节的习惯）；
    无明细 → 原样返回种类。
    """
    if not reason:
        return ""
    if detail:
        return f"{reason}-{detail}"
    return reason
