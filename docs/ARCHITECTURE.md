# 系统架构说明

## 真实项目形态

从现有代码结构判断，本项目是一个 AI 代理服务平台，而不是博客系统。仓库内不存在文章、分类、评论、标签、Markdown 渲染发布、后台发文等典型博客模块；相反，存在的是用户系统、API Key 管理、调用统计、OpenAI 兼容接口、MCP 工具与代理配置。

## 架构分层

### 前端层

前端全部是静态 HTML 页面，位于 `web/`:

- `index.html`: 首页、登录、注册
- `dashboard.html`: 用户控制台
- `admin.html`: 管理员后台

前端特点:

- 通过 Vue 3 CDN 直接挂载页面逻辑
- 使用 Axios 调用后端 API
- 使用 `localStorage` 保存用户 Token
- 不依赖打包器，不需要 Node 构建流程

### 应用层

FastAPI 主入口位于 `src/smithery_proxy/main.py`，负责:

- 启动应用
- 注册用户、管理员、聊天、RikkaHub、MCP 路由
- 提供根路径和静态页面
- 处理 CORS
- 提供全局异常处理

### 服务层

位于 `src/smithery_proxy/services/`:

- `database.py`: SQLite / SQLAlchemy 封装
- `auth_service.py`: JWT 认证
- `auth_manager.py`: Smithery 认证头管理
- `protocol_converter.py`: OpenAI 与内部格式转换
- `tool_manager.py`: 内置工具与 MCP 工具聚合
- `mcp_client.py`: 向 Smithery 聊天接口发起请求
- `mcp_playground_client.py`: 搜索 MCP 服务与工具

### 数据层

默认使用 SQLite 文件:

- 文件路径: `./users.db`
- 映射到容器内: `/app/users.db`

表模型定义在 `src/smithery_proxy/models/user_models.py` 中，启动时通过 SQLAlchemy 自动建表。

### 代理与接入层

项目有两层代理:

1. 宿主机 1Panel / Nginx 站点配置
2. Docker 内 Nginx 容器

这说明你的线上流量并不是直接到 FastAPI，而是经过反向代理分发和 TLS 处理。

## 请求路径

### 用户访问页面

```text
Browser
  -> 1Panel api.conf
  -> Docker Nginx
  -> FastAPI
  -> 返回 /、/dashboard.html、/admin.html
```

### 聊天接口

```text
Client
  -> /v1/chat/completions
  -> validate_request_auth()
  -> 解析 OpenAI 请求
  -> 工具意图检测 / 图片检测 / MCP 工具整合
  -> 转换为 Smithery 请求格式
  -> 请求 https://smithery.ai/api/chat
  -> 返回 OpenAI 兼容响应
  -> 写 usage_logs
```

### 管理员配置更新

```text
Admin Page
  -> /api/v1/admin/config/smithery-token
  -> 修改 .env
  -> 热重载 settings
  -> 立即生效
```

## 路由分组

### OpenAI 兼容

- `/v1/chat/completions`
- `/v1/models`
- `/v1/health`

### 用户系统

- `/api/v1/users/register`
- `/api/v1/users/login`
- `/api/v1/users/profile`
- `/api/v1/users/api-keys`
- `/api/v1/users/usage/stats`
- `/api/v1/users/usage/logs`

### 管理员系统

- `/api/v1/admin/users`
- `/api/v1/admin/api-keys`
- `/api/v1/admin/usage/stats`
- `/api/v1/admin/usage/logs`
- `/api/v1/admin/config/smithery-token`
- `/api/v1/admin/config/wos-session`

### RikkaHub 兼容层

- `/api/v1/rikkahub/chat/completions`
- `/api/v1/rikkahub/predict`
- `/api/v1/rikkahub/openai`
- `/api/v1/rikkahub/simple`

### MCP 管理层

- `/api/v1/mcp/servers`
- `/api/v1/mcp/servers/{server_id}`
- `/api/v1/mcp/servers/{server_id}/tools`
- `/api/v1/mcp/tools`
- `/api/v1/mcp/tools/test`
- `/api/v1/mcp/tools/refresh`
- `/api/v1/mcp/status`

## 前端与后端如何协作

### 首页 `index.html`

- 用户登录
- 用户注册
- 登录后根据 `is_admin` 决定进入用户页还是管理员页

### 控制台 `dashboard.html`

- 读取 `/api/v1/users/profile`
- 读取 `/v1/models`
- 管理自己的 API Key
- 查看自己的调用统计和调用日志
- 在线测试 `/v1/chat/completions`

### 管理后台 `admin.html`

- 查看所有用户与系统统计
- 管理全局 API Key
- 启停用户
- 删除用户
- 在线验证并更新 `SMITHERY_AUTH_TOKEN`
- 在线验证并更新 `SMITHERY_WOS_SESSION`

## 内置工具架构

`ToolManager` 将工具分为两类:

- 内置工具
- MCP 远程工具

内置工具包括:

- `web_search`
- `web_fetch`
- `code_executor`
- `document_manager`
- `data_analyzer`
- `image_analyzer`

MCP 工具通过 `MCPPlaygroundClient` 动态搜索和缓存。

## 模型与第三方依赖

### Smithery

核心对话能力最终由 `Smithery.ai` 承接，项目中做的是:

- 鉴权
- 请求清洗
- 格式适配
- 工具编排
- 页面和用户系统

### Gemini 视觉代理

图片分析工具使用独立的 OpenAI 兼容视觉接口，需要通过:

- `GEMINI_API_KEY`
- `GEMINI_BASE_URL`

来配置，不再建议在源码中写死。

## 当前架构特点

- 优点:
  - 页面简单，部署成本低
  - 后端功能集中，适合快速上线
  - OpenAI 兼容性强，便于接入现有客户端
  - 自带用户与管理后台

- 局限:
  - `chat.py` 体积偏大
  - SQLite 不适合大规模并发
  - 认证与第三方耦合较深
  - 前端为单文件页面，后续维护成本会逐步升高

