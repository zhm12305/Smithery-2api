# Smithery 2Api Proxy

这是一个部署在 Linux 服务器上的 AI 接口代理项目，不是传统博客 CMS。它提供了一个带登录页、用户控制台和管理员后台的 Web 面板，对外暴露 OpenAI 兼容接口，并将请求代理到 `Smithery.ai`，同时集成了 MCP 工具发现、RikkaHub 兼容接口和若干内置工具能力。

## 项目定位

- 面向终端用户提供 API Key 自助管理、调用统计和在线测试
- 面向管理员提供用户管理、系统统计、Smithery Token / `wos-session` 热更新
- 面向开发者提供 OpenAI 兼容的 `/v1/chat/completions`、`/v1/models` 等接口
- 面向扩展场景提供 MCP 服务器搜索、工具发现和工具调用测试

## 主要功能

- 用户注册、登录、JWT 鉴权
- 用户级 API Key 创建、删除、查看
- API 调用统计与日志记录
- OpenAI 兼容聊天接口
- 动态模型列表同步
- RikkaHub 兼容接口
- MCP 服务器搜索、工具列表、工具测试
- 内置工具:
  - `web_search`
  - `web_fetch`
  - `code_executor`
  - `document_manager`
  - `data_analyzer`
  - `image_analyzer`
- 管理员后台:
  - 用户启用/禁用/删除
  - API Key 管理
  - 全局使用统计
  - Smithery Token 验证与更新
  - `wos-session` 验证与更新

## 技术栈

### 后端

- Python 3.11
- FastAPI
- Uvicorn
- Pydantic / pydantic-settings
- SQLAlchemy
- passlib + bcrypt
- python-jose
- httpx / requests
- structlog / python-json-logger
- BeautifulSoup4
- pandas / numpy / matplotlib
- MCP Python SDK

### 前端

- 原生静态页面
- Vue 3 CDN 版
- Axios
- Font Awesome
- Google Fonts

### 数据与部署

- SQLite (`users.db`)
- Docker / Docker Compose
- Nginx
- 1Panel 反向代理配置
- Let's Encrypt 证书
- Cloudflare 源站接入

## 目录结构

```text
.
├─ src/smithery_proxy/          # FastAPI 主程序
│  ├─ api/v1/                   # 用户、管理员、聊天、MCP、RikkaHub 接口
│  ├─ models/                   # Pydantic / SQLAlchemy 模型
│  ├─ services/                 # 认证、数据库、协议转换、工具管理、MCP 客户端
│  ├─ tools/                    # 内置工具实现
│  └─ utils/                    # 日志、内容清洗、图片/文档检测
├─ web/                         # 登录页、用户控制台、管理员后台
├─ docker/nginx/                # 容器内 Nginx 配置
├─ data/                        # 运行时数据目录
├─ logs/                        # 运行日志
├─ documents/                   # 文档工具的运行时输出
├─ docker-compose.yml           # 容器编排
├─ Dockerfile                   # 应用镜像构建
├─ api.conf                     # 1Panel 上的站点 conf 示例
├─ start_server.py              # 启动入口
└─ fix-database-final.sh        # 数据库权限修复脚本
```

## 运行链路

### Web 页面

- `/` -> 登录/注册首页
- `/dashboard.html` -> 用户控制台
- `/admin.html` -> 管理员后台

### API 主链路

1. 客户端调用 `/v1/chat/completions`
2. 服务校验 Bearer Token
3. 服务解析 OpenAI 格式请求
4. 按需决定是否挂载或调用内置工具 / MCP 工具
5. 将请求转换为 Smithery 接受的消息结构
6. 请求 `Smithery.ai` 并返回 OpenAI 兼容响应
7. 将调用结果写入 `usage_logs`

## 部署概览

当前项目体现的是“双层反向代理”结构:

1. Cloudflare / 外部访问流量到 1Panel 站点
2. 1Panel `api.conf` 处理真实 IP、ACME、转发到本机 `8043`
3. Docker 内 Nginx 容器监听 `8043:443`
4. Docker 内 Nginx 再转发到 FastAPI 容器 `20179`
5. FastAPI 访问 SQLite、本地工具和外部 Smithery 服务

`20179` 端口也直接映射到宿主机，便于本地调试和健康检查。

## 数据库概览

当前默认数据库为本地 SQLite 文件 `users.db`，由 SQLAlchemy 自动建表。核心表:

- `users`
- `user_api_keys`
- `usage_logs`

详细说明见 [docs/DATABASE.md](docs/DATABASE.md)。

## 环境变量

至少需要关注以下配置:

- `SMITHERY_AUTH_TOKEN`
- `SMITHERY_WOS_SESSION`
- `JWT_SECRET_KEY`
- `DATABASE_URL`
- `GOOGLE_SEARCH_API_KEY`
- `GOOGLE_SEARCH_CX`
- `GEMINI_API_KEY`
- `GEMINI_BASE_URL`

请从 [`.env.example`](.env.example) 复制为 `.env` 后再填写真实值。

## 快速开始

### 本地运行

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python start_server.py
```

### Docker Compose

```bash
cp .env.example .env
docker compose up -d --build
```

服务默认监听:

- FastAPI: `http://localhost:20179`
- Docker Nginx HTTP: `http://localhost:8088`
- Docker Nginx HTTPS: `https://localhost:8043`

## 页面与接口说明

- 用户端接口见 [docs/API.md](docs/API.md)
- 架构说明见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- 部署说明见 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)
- 安全说明见 [docs/SECURITY.md](docs/SECURITY.md)
- GitHub 发布检查见 [docs/GITHUB_PUBLISH_CHECKLIST.md](docs/GITHUB_PUBLISH_CHECKLIST.md)

## 已知限制

- 当前数据库是单文件 SQLite，更适合轻量部署，不适合高并发多实例横向扩展
- `image_analyzer` 依赖额外的兼容视觉模型服务，需要额外配置
- MCP Playground 客户端部分行为仍带有推断和模拟逻辑
- 仓库内 `chat.py` 逻辑较大，后续适合拆分为更清晰的服务层
