# WechatBackEnd

微信客服后端服务，基于 FastAPI 构建的现代化 API 服务，提供用户管理、工单处理、出差记录填写、AI助手等功能。
包含 移动端模块以及管理后台模块
## 项目概述

本项目是一个为微信客服系统设计的后端服务，支持移动端和后台管理双端接口，并集成了AI助手功能。采用 FastAPI 框架构建，具备高性能、易扩展的特点。

## 技术栈

- **框架**: FastAPI
- **数据库**: MySQL (通过 SQLAlchemy/SQLModel)
- **缓存**: Redis
- **异步数据库驱动**: aiomysql
- **任务调度**: APScheduler
- **文件处理**: aiofiles, Pillow
- **AI服务**: 阿里百炼平台集成
- **安全**: JWT 认证, CORS 支持

## 项目结构

```
WechatBackEnd/
├── alembic/                 # 数据库迁移工具配置
├── app/                     # 主应用代码
│   ├── config.py           # 项目配置文件
│   ├── __init__.py         # 应用初始化
│   ├── db_services/        # 数据库服务层
│   ├── dependencies/       # 依赖注入
│   ├── external/           # 外部服务接口
│   ├── files/              # 文件操作
│   ├── logger/             # 日志系统
│   ├── models/             # 数据库模型
│   ├── routers/            # 路由定义
│   │   ├── AI/             # AI助手相关接口
│   │   ├── BM/             # 后台管理接口
│   │   └── MT/             # 移动端接口
│   ├── schemas/            # Pydantic 模型定义
│   ├── services/           # 业务逻辑服务
│   ├── tasks/              # 定时任务
│   └── utils/              # 工具函数
├── logs/                   # 日志文件目录
├── main.py                 # 应用入口
├── requirements.txt        # 项目依赖
├── scripts/                # 运维/迁移脚本（建表、清理等）
│   ├── migrate_trip.py     # 出差记录表建表/升级（幂等，二合一）
│   ├── migrate_expense.py  # 出差费用表建表/补列（幂等）
│   └── render_pdf_cache.py # PDF 渲染缓存工具
├── .env                    # 环境变量配置
└── README.md               # 项目说明文档
```

## 功能模块

### 1. 移动端接口 (MT)

位于 `app/routers/MT/` 目录下，提供移动端所需的各种接口：

- **用户管理**: 用户注册、登录、个人信息管理
- **工单管理**: 工单创建、查询、状态更新
- **出差记录填写**: 按天登记项目、工作内容、客户与起止时间，周期查询（详见下方「出差记录填写模块」）
- **出差费用报销**: 按发票登记票期、项目、报销种类与金额，一天可多笔（详见下方「出差费用报销模块」）
- **微信授权**: 微信登录、授权相关功能
- **AI助手**: 基于阿里百炼的大语言模型交互

### 2. 后台管理接口 (BM)

位于 `app/routers/BM/` 目录下，提供后台管理功能：

- **用户管理**: 用户信息管理、权限控制、软删除（停用）、重置登录密码（`PUT /BM/user/password/{user_id}`）
- **工单管理**: 工单审核、处理流程管理
- **出差记录管理**: 填写情况查询、按人汇总、Excel 导出
- **出差费用管理**: 费用明细查询、按结算月/姓名/项目/种类/票期筛选、Expenses 版式全量导出
- **后台信息管理**: 系统配置、公告等
- **RAG管理**: 检索增强生成功能管理
- **问卷管理**: 问卷创建、发布、结果统计
- **公司信息管理**: 企业相关信息维护

### 3. AI助手接口 (AI)

位于 `app/routers/AI/` 目录下，提供智能客服功能：

- **智能助理**: 基于大语言模型的对话机器人
- **自然语言处理**: 语义理解、意图识别

## 出差记录填写模块

面向公司出差员工按天登记「项目 / 工作内容 / 客户 / 工作时间」，每月 25 日为截止日；后台可查询填写情况并按结算月导出 Excel。

### 业务规则

| 规则 | 说明 |
|---|---|
| 结算周期 | `[上月 25 日, 本月 25 日]`，结算月取结束月（如 10-25 ~ 11-25 归属 `2026-11`） |
| 截止规则 | 今天 ≥ 25 号即进入新周期，上一周期自动关闭 —— 即"过了 25 号不能填" |
| 一天一条 | 同一用户同一天最多一条记录，由唯一索引 `uq_trip_user_date (user_id, trip_date)` 保证 |
| 截止前可改 | 记录所属周期未过截止日（25 日）时可 `PUT` 修改；截止后锁定只读，不再提供 update / delete |
| 可补填 | 周期内任意 `<= 今天` 的日期都能填，允许最后一天集中补录 |
| 字段长度 | `project` ≤50、`task` ≤500、`customer` ≤100、`remark` ≤500；系统只记录不解析内容 |
| 工时 | `total_worktime = (worktime_end - worktime_begin) × 24`；仅在服务端算一次并落库 |
| 时间范围 | 结束时间不得早于开始时间（不支持跨零点班次）；前端滚轮按此限制可选范围，接口同样校验 |
| 身份 | 只能填自己的，`user_id` 取自登录态；姓名不落库，展示时 join `user` 表 |

周期计算集中在 `app/utils/trip_cycle.py`（唯一事实来源），接口与前端都不自行推算日期。

### 数据表

`trip_record`：`id / user_id / trip_date / project / task / customer / worktime_begin / worktime_end / total_worktime / remark / cycle_key / create_at / update_at`

- `trip_date` = 用户日历上点选的那一天（业务主键级别的含义），不是提交时间；
- `cycle_key` = 归属结算月 `YYYY-MM`，封账快照，避免日后调整截止日导致历史账目被重算；
- `update_at` = 最后修改时间，改过才有值（后台列表显示「最后修改」）；
- 索引：`uq_trip_user_date (user_id, trip_date)` 唯一、`ix_trip_record_trip_date`、`ix_trip_cycle_key`；
- 外键 `trip_record_user_fk` 为 `ON DELETE RESTRICT`，防止误删用户连带抹掉历史记录。

### 接口

移动端（需登录）：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/trips/cycle` | 当前周期起止、`editable_until`（最后可填日）、`record_count` / `filled_days` 及本人记录 |
| POST | `/api/v1/trips/record` | 提交某天记录 `{trip_date, project, task, customer, worktime_begin, worktime_end, remark}`；重复提交返回 409 |
| PUT | `/api/v1/trips/record/{id}` | 修改本人记录（仅所属周期未截止时）；总时长由服务端重算，`trip_date` / `cycle_key` 不可改 |
| GET | `/api/v1/trips/records` | 本人某周期的记录列表 |

后台（需管理员）：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/BM/trip/cycles` | 最近 12 个结算月（下拉用） |
| GET | `/BM/trip/list` | 明细，支持 `cycle / name / project / trip_date` + 分页 |
| GET | `/BM/trip/export/excel` | 导出 xlsx，仅一个 sheet「Working Overview」（A~I 九列，与源表对齐、可直接贴回；Waiting time 列已去掉）。加 `all_data=true` 时忽略结算月与姓名/项目筛选，导出全部历史记录 |

### 建表 / 升级

项目没有 `create_all`，`alembic/versions` 为空，**表结构由脚本落地**（服务启动不建表）：

```bash
cd WechatBackEnd
./myenv/bin/python scripts/migrate_trip.py               # 幂等：空库建 v2，老库原地升到 v2
./myenv/bin/python scripts/migrate_trip.py --dry-run     # 只体检不改（上生产先跑这个）
./myenv/bin/python scripts/migrate_trip.py --move-to-task # 超长 project 原文搬进 task 再截断（推荐）
./myenv/bin/python scripts/migrate_trip.py --dedupe      # 清理"同一天多条"重复并建唯一索引
./myenv/bin/python scripts/migrate_trip.py --print-sql   # 只打印 v2 建表 DDL（给 DBA / 存档）
```

脚本做的事：建表（含唯一索引 `uq_trip_user_date`、外键 `ON DELETE RESTRICT`）；老表原地升级（`device_no / trip_reason → project`、补齐 `task / customer / worktime_* / total_worktime / remark / update_at`、删历史 `user_name` 列、回填总时长）；`project` 收敛到 50 字符时**默认不动超长历史数据**（只打印明细），确认后加 `--move-to-task`（原文搬进 task，不丢内容）或 `--truncate`（会丢字）；检测到重复数据时同样默认只报告并跳过建唯一索引，确认可清理时加 `--dedupe`（每组保留 id 最小的一条）。重复执行安全，已到位的步骤全部跳过。

### 实现要点

- **重复提交**：接口先查 `(user_id, trip_date)`，命中直接 409；数据库唯一键兜底并捕获 `IntegrityError` 同样转 409，并发双端提交也只会落一条；
- **时区**：库中 `DATETIME` 为 UTC 朴素时间，对外输出统一经 `to_cn()` 转北京时间，避免导出时间差 8 小时；
- **软删除联动**：用户删除改为 `is_active=False`（不物理删除），鉴权会校验该字段；出差记录因此始终可追溯，重新激活账号后历史记录仍在；
- **当前用户信息**：`GET /api/v1/users/info` 返回登录用户资料（供前端刷新后补齐姓名），该路由必须声明在 `GET /users/{user_id}` 之前。

## 出差费用报销模块

面向出差员工登记每张发票的费用（对应 `Daily Report in China` 的 Expenses 表）：票期、项目、报销种类、金额、注释。周期与出差记录同一套（每月 25 日截止），后台可查询并按 Expenses 版式全量导出 Excel。

### 与出差记录的关键差别

| 维度 | 出差记录 trip_record | 出差费用 expense_record |
|---|---|---|
| 一天几条 | 一天一条（唯一索引兜底） | **一天可以多条**，一天里可能有好几张发票 |
| 时间表示 | 单个 `trip_date` | `expense_date` + `expense_date_end`，一张票跨几天就填区间 |
| 姓名 | 不落库，join `user` | 同左（`name` 列在表里仍记 `user_id`） |
| 报销种类 | — | **固定下拉**，不接受自由填写；劳保用品 / 工具 / 其他必须补明细 |
| 删除 | 不提供 | 提供（仅本周期截止前） |

### 业务规则

| 规则 | 说明 |
|---|---|
| 结算周期 | 复用 `app/utils/trip_cycle.py`：`[上月 25 日, 本月 25 日]`，`cycle_key` 按**发票起始日期**归属 |
| 可填日期 | 只允许当前周期内、且不晚于今天的日期；跨天费用两端都要落在窗口内 |
| 截止前可改可删 | 记录所属周期截止日（25 日）之前允许 `PUT` / `DELETE`；截止后锁定只读 |
| 金额 | `DECIMAL(10,2)`，必须 > 0 且 ≤ 100000，服务端统一保留两位小数 |
| 报销种类 | 6 类固定选项，见 `app/utils/expense_reason.py`（字典唯一事实来源） |
| 劳保用品 / 工具 / 其他 | 选中后 `reason_detail` 必填（≤100 字），导出拼成「工具-22mm 套筒」 |
| 字段长度 | `project` ≤50（可空）、`explanation` ≤500、`reason` ≤20 |
| 身份 | 只能填自己的，`user_id` 取自登录态；改/删他人记录一律 404 |

报销种类字典（`app/utils/expense_reason.py`，接口 `GET /expenses/reasons` 下发，前端不硬编码）：

1. **交通工具**：出租车、滴滴车、公交车、大巴车、地铁、火车、飞机
2. **其他费用**：租车费、汽油费、过路费、住宿费、快递费、焊工
3. **业务招待费**：客户礼物、餐饮费
4. **劳保用品**（需明细）
5. **工具**（需明细）
6. **其他**（需明细）

### 数据表

`expense_record`：`id / user_id / expense_date / expense_date_end / project / reason / reason_detail / expense / explanation / cycle_key / create_at / update_at`

- `expense_date` 是发票产生日期，同时也是 `cycle_key` 的归属依据；`expense_date_end` 为空表示单日发票；
- 索引：`ix_expense_user_date (user_id, expense_date)`、`ix_expense_date`、`ix_expense_cycle_key`；**没有唯一键**（一天可多条）；
- 外键 `expense_record_user_fk` 为 `ON DELETE RESTRICT`，防止误删用户连带抹掉历史账目；
- 源表的 `Reimbursement date`（贴票报销日期）由财务线下填写，本系统不建列、不导出。

### 接口

移动端（需登录）：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/expenses/reasons` | 报销种类选项（类别 + 具体项 + 必填明细标记） |
| GET | `/api/v1/expenses/cycle` | 当期周期信息、本人明细、笔数与金额合计 |
| POST | `/api/v1/expenses/record` | 提交一笔 `{expense_date, expense_date_end?, project?, reason, reason_detail?, expense, explanation?}` |
| PUT | `/api/v1/expenses/record/{id}` | 修改本人一笔（仅所属周期截止前）；改日期会重新归属结算月 |
| DELETE | `/api/v1/expenses/record/{id}` | 删除本人一笔（仅所属周期截止前） |
| GET | `/api/v1/expenses/records` | 本人某周期的费用明细 |

后台（需管理员）：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/BM/expense/reasons` | 报销种类选项（筛选下拉用） |
| GET | `/BM/expense/cycles` | 最近 12 个结算月（下拉用） |
| GET | `/BM/expense/list` | 明细，支持 `cycle / name / project / reason_group / date_from / date_to` + 分页，返回 `total_amount` |
| GET | `/BM/expense/export/excel` | 全量导出 xlsx，工作表「Expenses」 |

### 导出版式（对齐源表 Expenses）

- 第 1 行：A1 写标题 `Expense`，D1 写金额合计（与源表同位置）；
- 第 2 行表头 6 列：`Date / Project / Name / Expense / Reason / Explanation`（源表最后一列 Reimbursement date 已去掉）；
- 数据从第 3 行开始，按**姓名 + 日期**排序，一个人的票据连在一起，便于按阶段贴票；
- `Date` 列：单日发票写真实日期（`yyyy-mm-dd`，可排序筛选），跨天发票写 `2025-12-27 ~ 2026-01-03` 文本（源表也是这么混排的）；
- `Reason` 列：劳保用品 / 工具 / 其他带明细，一格内写成「工具-22mm 套筒」；
- 同一天多张发票 = 多行；一张票跨多天 = 单行加区间文本。当前只做**全量导出**，忽略结算月与筛选条件。

### 建表

```bash
cd WechatBackEnd
python scripts/migrate_expense.py --print-sql   # 只打印建表 DDL
python scripts/migrate_expense.py --dry-run     # 只体检不改（上生产先跑这个）
python scripts/migrate_expense.py               # 执行：空库建表；已存在则只补缺失列/索引
```

与 `migrate_trip.py` 一样是幂等的：重复执行安全，已有列和数据不会被改动。

## 环境配置

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

在项目根目录创建 `.env` 文件，配置以下参数：

```env
# 数据库配置
DB_HOST=localhost
DB_PORT=3306
DB_USER=your_username
DB_PASSWORD=your_password
DB_NAME=wechat_backend

# Redis配置
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=

# 阿里百炼秘钥
ALI_ACCESS_KEY_ID=your_access_key_id
ALI_ACCESS_KEY_SECRET=your_access_key_secret

# JWT配置
JWT_SECRET_KEY=your_jwt_secret_key
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30

# 文件存储路径
ATTACHMENT_PATH=./attachments
DOCUMENT_PATH=./documents
```

### 3. 数据库初始化

使用 Alembic 进行数据库迁移：

```bash
# 创建新的迁移版本
alembic revision --autogenerate -m "Initial migration"

# 应用迁移
alembic upgrade head
```

> 说明：当前 `alembic/versions` 为空，服务启动也不会自动建表。出差记录表 `trip_record` 请使用 `scripts/migrate_trip.py` 创建/升级（幂等），出差费用表 `expense_record` 请使用 `scripts/migrate_expense.py`（幂等），详见上文对应模块的「建表」小节。

## 启动服务

### 开发模式

```bash
uvicorn app.main:app --reload
```

或者直接运行主文件：

```bash
python main.py
```

### 生产模式

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

服务将在 `http://localhost:8000` 上启动。

## API 文档

FastAPI 自动生成了交互式 API 文档：

- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

## 中间件

项目集成了以下中间件：

- **CORS**: 跨域资源共享支持
- **请求日志**: 记录所有进入的请求
- **生命周期管理**: 自动初始化和关闭 Redis 连接

## 数据库模型

项目使用 SQLModel 作为 ORM，支持以下核心数据模型：

- **User**: 用户信息（`name`、`email` 各自唯一，姓名即唯一身份；删除为软删除 `is_active=False`）
- **Ticket**: 工单信息
- **TripRecord**: 出差记录 / 工作日报（`user_id`、`trip_date`、`project`、`task`、`customer`、`worktime_begin`、`worktime_end`、`total_worktime`、`remark`、`cycle_key`、`create_at`、`update_at`）
- **ExpenseRecord**: 出差费用报销（`user_id`、`expense_date`、`expense_date_end`、`project`、`reason`、`reason_detail`、`expense`、`explanation`、`cycle_key`、`create_at`、`update_at`；一天可多条、一条可跨天）
- **Survey**: 问卷信息
- **RAG**: 知识库相关模型

## 缓存策略

使用 Redis 作为缓存和会话存储，支持：

- 会话管理
- 接口限流
- 数据缓存

## 错误处理

项目实现了统一的错误处理机制，包括：

- HTTP 异常处理
- 自定义业务异常
- 日志记录

## 安全措施

- JWT Token 认证
- 输入验证与清理
- SQL 注入防护
- CORS 策略配置
- 管理员可重置任意用户登录密码（`PUT /BM/user/password/{user_id}`）：不校验旧密码、仅允许管理员调用、操作人写入日志；JWT 中不含密码版本号，重置后该用户已登录的会话在 token 过期前仍有效

## 部署建议

1. 使用反向代理（如 Nginx）处理静态资源和 HTTPS
2. 配置进程管理器（如 Supervisor 或 systemd）管理服务
3. 设置合适的日志轮转策略
4. 使用容器化部署（Docker）

## 开发规范

- 遵循 PEP 8 代码风格
- 使用类型提示提高代码可读性
- 统一日志格式
- 接口返回统一的数据结构

## 测试

运行测试套件：

```bash
pytest
```

## 贡献

欢迎提交 Issue 和 Pull Request 来改进项目。