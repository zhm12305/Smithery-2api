# 数据库说明

## 当前数据库类型

项目当前使用 SQLite，而不是 MySQL/PostgreSQL 等独立数据库服务。

默认连接串:

```text
sqlite:///./users.db
```

数据库文件:

- 宿主机: `./users.db`
- 容器内: `/app/users.db`

## 表结构

当前核心表共三张:

### 1. `users`

用途:

- 保存用户账号信息
- 保存是否激活、是否管理员

主要字段:

- `id`
- `username`
- `email`
- `hashed_password`
- `is_active`
- `is_admin`
- `created_at`
- `updated_at`

### 2. `user_api_keys`

用途:

- 保存每个用户的调用密钥
- 绑定默认模型、描述、启用状态、使用次数

主要字段:

- `id`
- `user_id`
- `api_key`
- `name`
- `description`
- `model`
- `is_active`
- `created_at`
- `last_used_at`
- `usage_count`

### 3. `usage_logs`

用途:

- 记录每次模型调用
- 保存端点、状态码、Token 消耗和模型信息

主要字段:

- `id`
- `user_id`
- `api_key_id`
- `endpoint`
- `method`
- `status_code`
- `prompt_tokens`
- `completion_tokens`
- `total_tokens`
- `model`
- `created_at`

## 表关系

```text
users
  ├─ 1:N -> user_api_keys
  └─ 1:N -> usage_logs

user_api_keys
  └─ 1:N -> usage_logs
```

## 数据库如何初始化

初始化逻辑在 `src/smithery_proxy/services/database.py`:

- 创建 SQLAlchemy engine
- 创建 session factory
- 调用 `Base.metadata.create_all(bind=self.engine)` 自动建表

因此第一次启动时，如果数据库文件不存在，会自动生成。

## 数据库存储特点

### 优点

- 部署简单
- 不需要独立数据库容器
- 适合单机轻量服务

### 局限

- 不适合高并发写入
- 不适合多实例共享
- 容器挂载权限出错时容易出现只读问题
- 备份和迁移要依赖文件级操作

## 与 GitHub 发布的关系

`users.db` 属于运行时数据，不应提交到公开仓库，因为它可能包含:

- 用户名
- 邮箱
- 哈希密码
- API Key
- 调用日志

即使是测试数据，也建议从 GitHub 仓库中移除。

## 推荐改造方向

如果后续要正式对外服务，建议升级到:

- PostgreSQL
- MySQL

并引入:

- Alembic 迁移
- 备份策略
- 连接池参数调优

