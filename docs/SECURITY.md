# 安全说明

## 仓库中最敏感的内容

以下内容不应直接公开到 GitHub:

- `.env`
- `users.db`
- `api_keys.json`
- `logs/`
- `data/`
- `documents/`
- 任何证书文件:
  - `*.pem`
  - `*.key`
  - `*.crt`

## 已处理的公开仓库风险

本次整理已做的脱敏工作:

- 新增 `.gitignore`
- 将 `.env.example` 中的第三方密钥改为占位符
- 将默认 Google Search Key/CX 改为占位符
- 将图片分析服务的硬编码 API Key / 域名改为环境变量驱动

## 仍需你自己决定的事项

### 1. 是否公开域名

当前配置文件中仍可看出你的真实业务域名:

- `api.inter-trade.top`

如果你不希望公开真实域名，请在发布前继续改为示例域名。

### 2. 是否保留 1Panel / Cloudflare 结构

`api.conf` 暴露了:

- Cloudflare 回源模式
- 端口结构
- TLS 证书目录

如果这是你的真实生产结构，建议在公开前做适度泛化。

## 高风险项

### `docker.sock` 挂载

`docker-compose.yml` 中存在:

```text
/var/run/docker.sock:/var/run/docker.sock:ro
```

这意味着容器可以感知宿主机 Docker。即使是只读挂载，也属于敏感能力暴露。公开仓库时应在文档中明确这是高风险配置，并确认生产是否真的需要。

### 全开放 CORS

当前默认 CORS 接近全开放:

- `allow_origins=["*"]`
- `allow_methods=["*"]`
- `allow_headers=["*"]`

这对演示方便，但对生产环境不够收敛。

### SQLite 挂载权限

SQLite 文件挂载在容器环境中时，容易出现权限问题。仓库中已有专门修复脚本，说明这是历史上真实遇到的问题。

## 发布前安全检查

1. 确认 `.env` 未被加入版本控制。
2. 确认 `users.db` 不进入仓库。
3. 确认 `api_keys.json` 不进入仓库。
4. 确认 `.env.example` 只有占位符。
5. 确认所有第三方 Key 都已经轮换。
6. 确认管理员账号和测试账号密码已重置。
7. 确认是否要隐藏真实域名。
8. 确认是否要移除 `docker.sock` 挂载。
9. 确认是否要收紧 CORS。
10. 确认日志里没有残留敏感请求体。

## 最佳实践建议

- 将 JWT 密钥设置为高强度随机值
- 生产环境关闭无关调试日志
- 使用外部数据库替代 SQLite
- 将 Token 更新能力限制在内网或 VPN
- 将管理后台访问路径额外做网关保护
- 将第三方凭据统一收敛到密钥管理系统

