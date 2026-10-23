# 部署与运维

## Docker（推荐）

```sh
git clone https://github.com/ssseeesss83/HexBound.git
cd HexBound
cp .env.example .env
docker compose up -d --build
```

打开 `http://localhost:8000`。同局域网玩家访问服务器的局域网 IP 与 8000 端口。容器使用非 root 用户；存档位于 `adventure-data` 命名卷，容器重建不会删除存档。`docker compose down -v` 会删除存档卷，谨慎使用。

## Python

需要 Python 3.12。前端为原生 ES Modules，不需要 Node 构建或外部字体 CDN。

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
set -a
. ./.env
set +a
python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000 --workers 1
```

`.env` 是服务器配置文件，不会自动被 Python 加载；上面的 shell 命令显式载入它。Windows PowerShell 可直接设置 `$env:LLM_MODEL`、`$env:LLM_API_KEY` 等，再运行 uvicorn。不要将 Key 写入前端、提交到 Git 或发送到房间聊天。

## 模型

`LLM_BASE_URL` 指向 OpenAI-compatible API 的基础地址（通常以 `/v1` 结尾）；服务会调用其 `/chat/completions`。设置 `LLM_MODEL`、`LLM_API_KEY` 后重启服务。兼容服务应支持 JSON response format；本地无鉴权服务可使用任意非空占位 Key。模型调用超时后保留规则结果，错误不会触发重掷。

`LLM_TIMEOUT_SECONDS` 是一次请求的整体等待上限（默认 25 秒，允许 1–90 秒）。自由剧本生成最多请求 3000 输出 tokens；场景润色和角色扮演最多 900。生成失败保留大厅，不会静默替换为预设剧本。生成期间若其他玩家改变房间版本，结果不会覆盖新状态，房主同步后可重新开始。已经开始的混合冒险在等待模型时仍可暂停或聊天；过期回应会被丢弃。请求取消或服务重启会清除未完成的回应标记，避免一直显示“正在回应”。

## 公网访问

本项目包含 Python 服务与 WebSocket，不能仅部署到 GitHub Pages。公网使用可信 HTTPS 反向代理，转发同源 `/api` 与 WebSocket 升级请求。参考 Nginx location（TLS 证书与域名按环境配置）：

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 300s;
}
```

首版面向自托管的小型私团；邀请码和浏览器恢复令牌属于持有即授权。使用 HTTPS，勿公开邀请码。尚未提供账号系统、密码恢复、全局限流或多租户计费；开放到公网前建议部署入口认证、请求速率限制和备份。模型端点只由部署者配置，玩家不能指定任意网络目标。

## 存档与并发

必须运行 **1 个 worker / 1 个应用实例**。房间锁与在线状态位于该进程；SQLite 持久化房间与命令回执。多副本部署需要替换存储并加入跨进程消息与房间调度，不能直接增加 `--workers`。

备份 SQLite 时使用 SQLite backup API 或停服后复制数据库及 WAL，不能在写入期间仅复制主数据库文件。恢复时设置 `HEXBOUND_DB` 指向恢复文件；玩家保留原浏览器会话凭证即可继续。丢失凭证后首版不提供身份恢复；邀请码不能冒领现有角色。

## 验证

```sh
pip install -r requirements-dev.txt
python -m pytest -q
node --check frontend/app.js
```

存活检查：`GET /api/health`。测试使用独立临时数据库，不应连接实际团存档。GitHub Actions 自动执行同一组测试。
