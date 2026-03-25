# GitHub 发布检查清单

## 一、必须不要提交的文件

- `.env`
- `users.db`
- `api_keys.json`
- `venv/`
- `logs/`
- `data/`
- `documents/`
- 证书文件
- 运行时备份文件

## 二、发布前必须确认的配置

- `.env.example` 中只保留占位符
- `JWT_SECRET_KEY` 没有写入真实值
- `SMITHERY_AUTH_TOKEN` 没有写入真实值
- `SMITHERY_WOS_SESSION` 没有写入真实值
- `GOOGLE_SEARCH_API_KEY` 没有写入真实值
- `GEMINI_API_KEY` 没有写入真实值

## 三、建议你手动决定的内容

### License

仓库目前没有自动添加 `LICENSE`，因为许可证属于你的法律选择。发布前请自行决定:

- `MIT`
- `Apache-2.0`
- `GPL-3.0`
- `All Rights Reserved`

### 域名脱敏

如果你不想暴露真实线上域名，请将:

- `api.inter-trade.top`
- `gemini.inter-trade.top`

替换为示例域名。

## 四、GitHub 仓库建议文件

本次已补充:

- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/DEPLOYMENT.md`
- `docs/API.md`
- `docs/DATABASE.md`
- `docs/SECURITY.md`
- `CONTRIBUTING.md`
- `.gitignore`

## 五、本地初始化 Git 示例

```bash
git init
git add .
git commit -m "Initial public release"
git branch -M main
git remote add origin <your-github-repo-url>
git push -u origin main
```

## 六、正式推送前再检查一次

```bash
git status
git diff --cached
```

重点确认:

- 没有 `.env`
- 没有数据库文件
- 没有日志
- 没有虚拟环境
- 没有 API Key

## 七、推荐补充

- GitHub 仓库描述
- Topics 标签
- Release 版本说明
- LICENSE
- Issue / PR 模板

