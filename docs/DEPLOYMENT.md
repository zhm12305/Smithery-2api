# 部署说明

## 部署形态

当前项目针对 Linux 服务器部署，结合:

- 1Panel
- Docker Compose
- Nginx
- Let's Encrypt
- Cloudflare

## 容器结构

`docker-compose.yml` 定义了两个服务:

### 1. `smithery-claude-proxy`

职责:

- 运行 FastAPI 应用
- 暴露内部服务端口 `20179`
- 挂载数据库、日志、文档、配置文件

关键点:

- 容器镜像来自项目内 `Dockerfile`
- 端口映射: `20179:20179`
- 健康检查: `http://localhost:20179/`
- 持久化挂载:
  - `./data:/app/data`
  - `./logs:/app/logs`
  - `./users.db:/app/users.db`
  - `./documents:/app/documents`
  - `./api_keys.json:/app/api_keys.json`
  - `./src:/app/src`
  - `./web:/app/web`
  - `./start_server.py:/app/start_server.py`

### 2. `nginx`

职责:

- 对外暴露 HTTP/HTTPS
- 代理到 FastAPI 容器
- 处理 TLS 证书

关键点:

- 端口映射:
  - `8088:80`
  - `8043:443`
- 读取:
  - `docker/nginx/nginx.conf`
  - `docker/nginx/conf.d/smithery.conf`
- 证书目录:
  - `/etc/letsencrypt`
  - `/var/lib/letsencrypt`

## Dockerfile 说明

`Dockerfile` 的执行流程:

1. 基于 `python:3.11-slim`
2. 安装系统依赖 `gcc`、`curl`
3. 安装 `requirements.txt`
4. 复制源码
5. 创建 `/app/data`、`/app/logs`、`/app/documents`
6. 创建非 root 用户 `app`
7. 启动 `python start_server.py`

## 1Panel `api.conf` 的作用

`api.conf` 不是容器内 Nginx 配置，而是 1Panel 站点层配置。它的作用包括:

- 监听 `api.inter-trade.top`
- 识别 Cloudflare 真实 IP
- 放行 `/.well-known/acme-challenge/`
- 将请求转发到本机 `https://127.0.0.1:8043`

这意味着你的实际线上访问链路是:

```text
Internet
  -> Cloudflare
  -> 1Panel Nginx(api.conf)
  -> localhost:8043
  -> Docker Nginx
  -> FastAPI:20179
```

## Docker 内 Nginx 的作用

`docker/nginx/conf.d/smithery.conf` 负责:

- 80 端口重定向到 443
- 加载 Let's Encrypt 证书
- 代理到 `smithery-claude-proxy:20179`
- 设置 HSTS、安全头、上传体积限制

## 启动方式

### 推荐

```bash
cp .env.example .env
docker compose up -d --build
```

### 裸运行

```bash
pip install -r requirements.txt
python start_server.py
```

## 关键端口

- `20179`: FastAPI 应用本体
- `8088`: Docker Nginx HTTP
- `8043`: Docker Nginx HTTPS

如果 1Panel 站点已接管域名，一般最终对外只暴露标准 80/443，由 1Panel 转发。

## 环境变量

### 必填

- `SMITHERY_AUTH_TOKEN`
- `SMITHERY_WOS_SESSION`
- `JWT_SECRET_KEY`

### 可选但推荐

- `GOOGLE_SEARCH_API_KEY`
- `GOOGLE_SEARCH_CX`
- `GEMINI_API_KEY`
- `GEMINI_BASE_URL`
- `HTTP_PROXY`
- `HTTPS_PROXY`

## 数据持久化

本项目当前没有独立数据库容器，数据直接落在宿主机文件中:

- `users.db`
- `data/`
- `logs/`
- `documents/`

这类文件必须做备份，不建议直接提交到 GitHub。

## 数据库权限问题

仓库内包含 `fix-database-final.sh`，作用是:

- 停止容器
- 备份 `users.db`
- 修复文件权限
- 重建并重启容器
- 检查是否仍有 `readonly database` 错误

适用场景:

- Docker 容器内 SQLite 无法写入
- 宿主机挂载文件权限不正确
- 迁移服务器后 UID/GID 变化

## 发布到新服务器的建议步骤

1. 上传代码，但不要上传 `.env`、`users.db`、`api_keys.json`
2. 在服务器上复制 `.env.example` 为 `.env`
3. 填写真实 Token、JWT、第三方 API Key
4. 准备证书或由 1Panel / Let's Encrypt 自动签发
5. 执行 `docker compose up -d --build`
6. 检查:
   - `/v1/health`
   - `/api/v1/mcp/status`
   - 页面是否可正常登录

## 生产环境建议

- 使用外部数据库替代 SQLite
- 收紧 CORS
- 不要在容器中挂载 `docker.sock`，除非你明确需要
- 将 `src` 挂载仅用于开发环境，生产环境建议使用镜像内代码
- 给日志与数据库做定时备份

