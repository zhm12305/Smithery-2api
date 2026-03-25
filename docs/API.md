# API 说明

## 认证方式

项目中有两套认证:

### 1. 用户后台认证

- 通过 `/api/v1/users/login` 获取 JWT
- 后续请求头:

```http
Authorization: Bearer <jwt_token>
```

### 2. 模型调用认证

- 通过用户后台生成 API Key
- 调用 `/v1/chat/completions` 等接口时使用:

```http
Authorization: Bearer sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

## 用户接口

前缀: `/api/v1/users`

### `POST /register`

功能:

- 注册新用户

请求体:

```json
{
  "username": "demo",
  "email": "demo@example.com",
  "password": "123456"
}
```

### `POST /login`

功能:

- 用户登录
- 返回 JWT

### `GET /profile`

功能:

- 获取当前用户资料

### `GET /api-keys`

功能:

- 获取当前用户的 API Key 列表

### `POST /api-keys`

功能:

- 创建新的 API Key

请求体:

```json
{
  "name": "My App",
  "description": "for test",
  "model": "claude-haiku-4.5"
}
```

### `DELETE /api-keys/{api_key_id}`

功能:

- 删除当前用户自己的 API Key

### `GET /usage/stats`

功能:

- 获取当前用户的统计信息

### `GET /usage/logs`

功能:

- 获取当前用户的调用日志

## 管理员接口

前缀: `/api/v1/admin`

需要当前登录用户 `is_admin=true`。

### 用户管理

- `GET /users`
- `GET /users/{user_id}`
- `PUT /users/{user_id}/status`
- `DELETE /users/{user_id}`

### API Key 管理

- `GET /users/{user_id}/api-keys`
- `GET /api-keys`
- `PUT /api-keys/{api_key_id}`
- `DELETE /api-keys/{api_key_id}`

### 系统统计

- `GET /usage/stats`
- `GET /usage/logs`

### Smithery 配置管理

- `GET /config/smithery-token`
- `POST /config/smithery-token/verify`
- `POST /config/smithery-token`
- `GET /config/wos-session`
- `POST /config/wos-session/verify`
- `POST /config/wos-session`

## OpenAI 兼容接口

前缀: `/v1`

### `POST /chat/completions`

功能:

- 接收 OpenAI 风格消息
- 支持流式和非流式响应
- 支持工具调用
- 支持部分多模态消息结构

示例:

```json
{
  "model": "claude-haiku-4.5",
  "messages": [
    {
      "role": "user",
      "content": "你好，请介绍一下你自己"
    }
  ],
  "stream": false
}
```

### `GET /models`

功能:

- 返回可用模型列表
- 包含内置模型
- 可尝试同步 Smithery 远端模型

### `GET /health`

功能:

- 健康检查

## RikkaHub 兼容接口

前缀: `/api/v1/rikkahub`

### 支持路径

- `POST /chat/completions`
- `POST /predict`
- `POST /openai`
- `POST /simple`

用途:

- 将当前服务包装为另一种更简化的返回格式
- 最终底层仍会调用现有聊天能力

## MCP 接口

前缀: `/api/v1/mcp`

### `GET /servers`

功能:

- 搜索可用 MCP 服务器

### `GET /servers/{server_id}`

功能:

- 获取 MCP 服务器详情

### `GET /servers/{server_id}/tools`

功能:

- 获取 MCP 服务器工具列表

### `POST /tools/test`

功能:

- 测试指定 MCP 工具调用

### `GET /tools`

功能:

- 获取汇总后的 MCP 工具定义

### `POST /tools/refresh`

功能:

- 刷新工具缓存

### `GET /status`

功能:

- 查看 MCP 功能状态与配置

## 内置工具清单

由 `ToolManager` 管理:

- `web_search`: Google Custom Search 搜索
- `web_fetch`: 抓取网页并转 Markdown
- `code_executor`: 执行 Python / JavaScript
- `document_manager`: 读写 `documents/` 目录文档
- `data_analyzer`: 数据统计、相关性、图表
- `image_analyzer`: 调用额外视觉模型服务分析图片

## 重要说明

- `/v1/chat/completions` 使用的是用户 API Key，不是管理员 JWT
- `/api/v1/*` 用户与管理员后台接口使用的是 JWT
- 某些工具依赖额外第三方配置，未配置时会返回明确错误

