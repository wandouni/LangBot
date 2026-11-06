# 本地应用中心栈

这套 Compose 把「浏览器 5300 → 网关 → LangBot / SqlBot」的本地联调拓扑固化成文件，解决之前**改代码靠 `docker cp` 临时塞进容器、容器一重建就丢**的问题。

一句话规矩：**应用代码只能进镜像，不能进容器。** 改完代码执行 `./deploy/local/build-image.sh`，再执行 `./deploy/local/deploy.sh`；不要再对 `vocational-langbot-core` 使用 `docker cp` 或 `docker exec` 改源码。

## 它管什么

| 容器 | 作用 | 宿主机入口 |
| --- | --- | --- |
| `portal_gateway` | nginx 唯一浏览器入口，按路径分流 | `GATEWAY_LAN_IP:5300`、`127.0.0.1:5300` |
| `vocational-langbot-core` | LangBot 主服务 | 仅 `127.0.0.1:5302` 调试口 |
| `sqlbot` | SqlBot，`CONTEXT_PATH=/sqlbot`，开启 LangBot SSO | `8010`（HTTP）、`8011`（MCP 调试） |
| `vocational-langbot-runtime` | 插件运行时 | 仅 `127.0.0.1:5401` 调试口 |

浏览器地址是 `http://<GATEWAY_LAN_IP>:5300/` 和 `http://<GATEWAY_LAN_IP>:5300/sqlbot/`。LangBot 自己的 5300 不再暴露给浏览器，避免 `/sqlbot/` 被前端路由兜底。

## 首次准备

1. 网络只建一次（Compose 里声明为 `external`，避免误删别的容器）：
   ```bash
   docker network create vocational-langbot-net
   ```
2. 复制配置并填写本机绝对路径、镜像标签和密钥：
   ```bash
   cp deploy/local/.env.example deploy/local/.env
   chmod 600 deploy/local/.env
   ```
   - `.env` 含数据库、SSO 与 API 密钥，权限保持 `600`；`deploy.sh` 每次启动也会自动收紧
   - `LANGBOT_DATA_DIR`：现有环境是 `<LangBot 仓库>/data/docker`
   - `SQLBOT_DATA_DIR`：现有环境是 `<SQLBot 仓库>/data`
   - `SQLBOT_SSO_SHARED_SECRET`：必须同时等于 `data/docker/config.yaml` 里的 `sqlbot.sso.shared_secret`
   - `SQLBOT_DEFAULT_PWD`：SqlBot 本地账号的初始密码，必须显式填写；启动时会把仍使用出厂默认口令的账号轮换为该值
   - `GATEWAY_LAN_IP`：本机非回环地址（回环由 Compose 自动再加一条 5300 映射）
3. 构建镜像并启动：
   ```bash
   ./deploy/local/build-image.sh
   ./deploy/local/deploy.sh --all
   ```

`build-image.sh` 会生成 `langbot:local-<版本>-<12位提交号>`；工作树有未提交改动时追加 `-dirty-<时间戳>`，并把标签写回 `.env` 的 `LANGBOT_IMAGE`。网关镜像也一起构建并写回 `PORTAL_GATEWAY_IMAGE`。

## 日常改代码

```bash
./deploy/local/build-image.sh   # 把当前工作树（含未提交改动）打进镜像
./deploy/local/deploy.sh        # 只重建 LangBot 容器
```

`deploy.sh` 不带参数时只动 `vocational-langbot-core`，SqlBot、网关和插件运行时不受影响；`deploy.sh --all` 才重建整套栈。

为什么这样能根治：镜像层是只读的，容器每次重建都从镜像重新展开，所以工作树里的 `embed.py`、`web_page_bot.yaml`、`widget.js` 和重新构建的 `web/dist` 必须由 Dockerfile 在构建阶段产生。`docker cp` 改的是容器可写层，`docker restart` 看起来还在，`docker rm`/`compose up` 重建后必然丢失——这正是之前的问题。

## 验证

```bash
# 应用中心开关（配置推导，不是探活）
curl -s http://127.0.0.1:5302/api/v1/system/info | python3 -m json.tool | grep -A4 portal

# 网关分流
curl -s http://127.0.0.1:5300/sqlbot/ | grep -o '<title>[^<]*</title>'   # SQLBot
curl -s http://127.0.0.1:5300/ | grep -o '<title>[^<]*</title>'          # LangBot

# 内部开票接口不得对公网暴露
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  http://127.0.0.1:5300/sqlbot/api/v1/system/langbot/sso/ticket           # 404
```

SSO 全链路再确认一次：应用中心点击 SqlBot 能跳到 `/sqlbot/#/login?sso_ticket=...` 并自动进入，不需要再输 SqlBot 密码。

## 回滚

- 只回滚 LangBot 代码：把 `.env` 的 `LANGBOT_IMAGE` 改回 `deploy/local/.last-image` 的上一个标签（或任意旧镜像），再 `./deploy/local/deploy.sh`。
- 关闭应用中心：`.env` 里 `PORTAL_ENABLED=false` 或 `PORTAL_SQLBOT_ENABLED=false`，重建 LangBot。
- 整栈下线：`cd deploy/local && docker compose --env-file .env down`。数据都在宿主机 bind mount 里，不会随容器删除。

## 注意

- `docker compose down` 不会删除 `external` 网络 `vocational-langbot-net`；要清理请确认没有其他容器在用。
- SqlBot 必须单 worker（镜像 `start.sh` 已固定），否则 SSO 票据的 nonce 不共享。
- SqlBot 自带健康检查探测 `/sqlbot`（无尾斜杠）会 401 误报，Compose 里已改为探测 `/sqlbot/`。
- `.env` 含密钥，已被 `deploy/local/.gitignore` 忽略，不要提交。
