# Contributing

## 开发环境

建议使用:

- Python 3.11
- 虚拟环境
- Docker Compose

## 本地启动

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python start_server.py
```

或:

```bash
docker compose up -d --build
```

## 提交前请确认

- 不要提交 `.env`
- 不要提交 `users.db`
- 不要提交 `api_keys.json`
- 不要提交 `logs/`、`data/`、`documents/`
- 如果新增配置项，请同步更新 `.env.example`
- 如果新增接口，请同步更新 `docs/API.md`
- 如果修改部署结构，请同步更新 `docs/DEPLOYMENT.md`

## 代码风格建议

- 尽量保持现有 FastAPI + service 分层结构
- 新增敏感配置时优先使用环境变量
- 避免在源码中硬编码第三方密钥
- 复杂逻辑优先拆到 `services/` 而不是继续堆进路由文件

## 文档要求

如果你的改动会影响以下内容，请同步更新对应文档:

- 功能定位 -> `README.md`
- 架构 -> `docs/ARCHITECTURE.md`
- 部署 -> `docs/DEPLOYMENT.md`
- API -> `docs/API.md`
- 数据库 -> `docs/DATABASE.md`
- 安全 -> `docs/SECURITY.md`

