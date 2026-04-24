# WechatBackEnd

微信客服后端服务，基于 FastAPI 构建的现代化 API 服务，提供用户管理、工单处理、AI助手等功能。
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
├── .env                    # 环境变量配置
└── README.md               # 项目说明文档
```

## 功能模块

### 1. 移动端接口 (MT)

位于 `app/routers/MT/` 目录下，提供移动端所需的各种接口：

- **用户管理**: 用户注册、登录、个人信息管理
- **工单管理**: 工单创建、查询、状态更新
- **微信授权**: 微信登录、授权相关功能
- **AI助手**: 基于阿里百炼的大语言模型交互

### 2. 后台管理接口 (BM)

位于 `app/routers/BM/` 目录下，提供后台管理功能：

- **用户管理**: 用户信息管理、权限控制
- **工单管理**: 工单审核、处理流程管理
- **后台信息管理**: 系统配置、公告等
- **RAG管理**: 检索增强生成功能管理
- **问卷管理**: 问卷创建、发布、结果统计
- **公司信息管理**: 企业相关信息维护

### 3. AI助手接口 (AI)

位于 `app/routers/AI/` 目录下，提供智能客服功能：

- **智能助理**: 基于大语言模型的对话机器人
- **自然语言处理**: 语义理解、意图识别

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

- **User**: 用户信息
- **Ticket**: 工单信息
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