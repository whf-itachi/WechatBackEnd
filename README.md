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
│   ├── init_trip_table.py  # 出差记录表初始化/升级（幂等）
│   └── sql/trip_record.sql # 出差记录表 DDL
├── .env                    # 环境变量配置
└── README.md               # 项目说明文档
```

## 功能模块

### 1. 移动端接口 (MT)

位于 `app/routers/MT/` 目录下，提供移动端所需的各种接口：

- **用户管理**: 用户注册、登录、个人信息管理
- **工单管理**: 工单创建、查询、状态更新
- **出差记录填写**: 按天登记出差原因、周期查询（详见下方「出差记录填写模块」）
- **微信授权**: 微信登录、授权相关功能
- **AI助手**: 基于阿里百炼的大语言模型交互

### 2. 后台管理接口 (BM)

位于 `app/routers/BM/` 目录下，提供后台管理功能：

- **用户管理**: 用户信息管理、权限控制、软删除（停用）
- **工单管理**: 工单审核、处理流程管理
- **出差记录管理**: 填写情况查询、按人汇总、Excel 导出
- **后台信息管理**: 系统配置、公告等
- **RAG管理**: 检索增强生成功能管理
- **问卷管理**: 问卷创建、发布、结果统计
- **公司信息管理**: 企业相关信息维护

### 3. AI助手接口 (AI)

位于 `app/routers/AI/` 目录下，提供智能客服功能：

- **智能助理**: 基于大语言模型的对话机器人
- **自然语言处理**: 语义理解、意图识别

## 出差记录填写模块

面向公司出差员工按天登记「出差原因」，每月 25 日为截止日；后台可查询填写情况并按结算月导出 Excel。

### 业务规则

| 规则 | 说明 |
|---|---|
| 结算周期 | `[上月 25 日, 本月 25 日]`，结算月取结束月（如 10-25 ~ 11-25 归属 `2026-11`） |
| 截止规则 | 今天 ≥ 25 号即进入新周期，上一周期自动关闭 —— 即"过了 25 号不能填" |
| 一天一条 | 同一用户同一天最多一条记录，由唯一索引 `uq_trip_user_date (user_id, trip_date)` 保证 |
| 写入即锁定 | 只提供新增接口，没有 update / delete；已填日期前端只做只读展示 |
| 可补填 | 周期内任意 `<= 今天` 的日期都能填，允许最后一天集中补录 |
| 内容自由 | `trip_reason` 为自由文本（≤1000 字，保留换行），系统只记录不解析 |
| 身份 | 只能填自己的，`user_id` 取自登录态；姓名不落库，展示时 join `user` 表 |

周期计算集中在 `app/utils/trip_cycle.py`（唯一事实来源），接口与前端都不自行推算日期。

### 数据表

`trip_record`：`id / user_id / trip_date / trip_reason / cycle_key / create_at`

- `trip_date` = 用户日历上点选的那一天（业务主键级别的含义），不是提交时间；
- `cycle_key` = 归属结算月 `YYYY-MM`，封账快照，避免日后调整截止日导致历史账目被重算；
- 索引：`uq_trip_user_date (user_id, trip_date)` 唯一、`ix_trip_record_trip_date`、`ix_trip_cycle_key`；
- 外键 `trip_record_user_fk` 为 `ON DELETE RESTRICT`，防止误删用户连带抹掉历史记录。

### 接口

移动端（需登录）：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/trips/cycle` | 当前周期起止、`editable_until`（最后可填日）、`record_count` / `filled_days` 及本人记录 |
| POST | `/api/v1/trips/record` | 提交某天记录 `{trip_date, trip_reason}`；重复提交返回 409 |
| GET | `/api/v1/trips/records` | 本人某周期的记录列表 |

后台（需管理员）：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/BM/trip/cycles` | 最近 12 个结算月（下拉用） |
| GET | `/BM/trip/list` | 明细，支持 `cycle / name / reason / trip_date` + 分页 |
| GET | `/BM/trip/summary` | 按人汇总：出差天数、已填日期、最后提交时间、未填人员名单 |
| GET | `/BM/trip/export/excel` | 导出 xlsx，含「出差明细」「人员汇总」两个 sheet |

### 建表 / 升级

项目没有 `create_all`，`alembic/versions` 为空，**表需手动创建**：

```bash
cd WechatBackEnd
./myenv/bin/python scripts/init_trip_table.py            # 幂等，重复执行安全
./myenv/bin/python scripts/init_trip_table.py --dedupe   # 仅在历史数据存在同一天多条时使用
```

脚本会做三件事：建表（带唯一索引）、识别旧结构自动升级（`device_no → trip_reason`、补索引、删 `user_name`、外键改 RESTRICT）、检测到重复数据时**默认只报告不删数据**并跳过建唯一索引，确认可清理时加 `--dedupe`（每组保留 id 最小的一条）。

### 实现要点

- **重复提交**：接口先查 `(user_id, trip_date)`，命中直接 409；数据库唯一键兜底并捕获 `IntegrityError` 同样转 409，并发双端提交也只会落一条；
- **时区**：库中 `DATETIME` 为 UTC 朴素时间，对外输出统一经 `to_cn()` 转北京时间，避免导出时间差 8 小时；
- **软删除联动**：用户删除改为 `is_active=False`（不物理删除），鉴权会校验该字段；出差记录因此始终可追溯，重新激活账号后历史记录仍在；
- **当前用户信息**：`GET /api/v1/users/info` 返回登录用户资料（供前端刷新后补齐姓名），该路由必须声明在 `GET /users/{user_id}` 之前。

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

> 说明：当前 `alembic/versions` 为空，服务启动也不会自动建表。出差记录表 `trip_record` 请使用 `scripts/init_trip_table.py` 创建（幂等），详见上文「出差记录填写模块 → 建表 / 升级」。

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
- **TripRecord**: 出差记录（`user_id`、`trip_date`、`trip_reason`、`cycle_key`、`create_at`）
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