# 前置登录与应用中心

`portal_gateway` 是浏览器唯一入口，占用原来的 5300 端口：

```text
Browser  http://<host>:5300
   |
   v
portal_gateway (nginx)
   |                                  |
   | 其他路径                          | /sqlbot/*
   v                                  v
langbot:5300 (宿主 127.0.0.1:5301)  sqlbot:8000/sqlbot/*
```

- LangBot 继续提供 `/login`（账号密码 + CAS 2.0）和 `/portal` 应用中心。
- SqlBot 设置 `CONTEXT_PATH=/sqlbot`，网关保留前缀转发，因此静态资源、`xpack_static`、API、SSE 都在同一前缀下。
- 网关把内部开票接口 `/sqlbot/api/v1/system/langbot/sso/ticket` 直接返回 404；LangBot 通过 compose 网络直连 `http://sqlbot:8000` 调用它。
- 访问日志不记录 query string，避免后续新增接口把一次性凭据写进日志；票据本身放在 URL fragment，不会发送到服务器。

## 构建

```bash
./deploy/prod/build-image.sh                 # LangBot + 网关
SQLBOT_SOURCE_DIR=/path/to/SQLBot ./deploy/prod/build-image.sh   # 额外构建 SqlBot
./deploy/prod/ship-image.sh                  # 传输 .last-*-image 记录的全部镜像
```

网关镜像在有外网的构建机上生成，离线主机只执行 `docker load`，不需要基础镜像，
也不需要在服务器上安装 nginx。

## 首次切换

1. 备份：`sudo ./backup.sh`。
2. 加载三个镜像：LangBot、SqlBot、`langbot-portal-gateway`。
3. 复制 `.env.example` 为 `.env`，填写 `SQLBOT_SECRET_KEY`、`SQLBOT_POSTGRES_PASSWORD`、
   `SQLBOT_SSO_SHARED_SECRET`（`openssl rand -hex 32`），并确认 `PUBLIC_ORIGIN`。
4. 先保持 `PORTAL_ENABLED=false`、`PORTAL_SQLBOT_ENABLED=false` 启动：
   `sudo docker compose --env-file .env up -d`。
5. 验证：
   ```bash
   curl -i http://<host>:5300/healthz
   curl -i http://<host>:5300/gateway-healthz
   curl -i http://<host>:5300/sqlbot/
   curl -i -X POST http://<host>:5300/sqlbot/api/v1/system/langbot/sso/ticket   # 必须 404
   ```
6. 打开应用中心前，把两个开关改为 `true` 并重启 LangBot：
   ```bash
   sudo docker compose --env-file .env up -d langbot
   ```

## 回退

1. `PORTAL_SQLBOT_ENABLED=false`：登录后只显示 LangBot。
2. `PORTAL_ENABLED=false`：恢复登录后直接进入 `/home`。
3. 停网关，把 LangBot 端口改回 `5300:5300`，恢复旧 `.env`。

## 已知限制

- SqlBot 必须保持单 worker（镜像里的 `start.sh` 已固定 `--workers 1`），否则内存中的
  ticket/nonce 不共享；重启后未兑换的票据失效，用户重新从应用中心进入即可。
- 本期不做跨系统单点退出：SqlBot 退出不影响 LangBot 会话。
- SqlBot 自身的密码登录默认仍可用；如需强制只走门户，需另行关闭其第三方登录。
