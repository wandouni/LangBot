# 豆包 Seedream 生图 MCP 接入 Runbook

> **本文档的读者是 AI Agent，不是人。**
> 读到本文档即视为接到任务：把当前机器上的 Claude Code / Codex / WorkBuddy 配置好豆包 Seedream 生图 MCP，并验证到「能真实出图」为止。
> 人类用户如果自己看：跳到 [§9.1 一键安装提示词](#91-粘贴给-ai-的一键安装提示词)，把那段话发给你的 AI 即可，不需要读完全文。

---

## 0. 任务契约（先读，违反即失败）

**目标**：三个客户端各有一条名为 `seedream` 的 MCP 服务，握手成功、工具可列出、能返回本地图片路径。

**你可以做的**

- 读取用户主目录下的客户端配置、运行仓库内的 `scripts/setup_seedream_mcp.py`。
- 备份后写入下面这三个文件（**仅限这三个**）：
  - `~/.claude.json` 的 `mcpServers` 字段
  - `~/.codex/config.toml` 的 `[mcp_servers.seedream]` 段
  - `~/.workbuddy/mcp.json` 的 `mcpServers` 字段
- 调用 `https://ai.ctaigw.cn/v1/images/generations` 做一次探测请求（只为判断授权状态）。

**你不可以做的**

- 把网关 Token 写进仓库文件、提交、日志、聊天回复或任何文档；只允许它存在于上述客户端配置里。
- 在命令行里用明文 `--token xxx` 传递 Token（会进 shell history）。用环境变量。
- 修改网关、申请密钥、猜测未提供的 ID。
- 在握手/出图没成功时报告「已完成」。验证失败就如实说失败，并给出错误码和下一步。

**Token 从哪来（按此顺序取，不要问用户要第二遍）**

1. 环境变量 `ARK_API_KEY` 或 `SEEDREAM_API_KEY`
2. `~/.claude/settings.json` 的 `env.ANTHROPIC_AUTH_TOKEN`（cc-switch 管理的网关 Key）
3. 都没有 → 问用户要，且只在这一步问一次

---

## 1. 硬事实表（禁止自行推断或改写）

| 项 | 值 | 说明 |
| --- | --- | --- |
| 网关 Base URL | `https://ai.ctaigw.cn/v1` | **必须带 `/v1`**。客户端拼成 `{base_url}/images/generations`；少了 `/v1` 返回 `401 api-key access forbit` |
| 生图端点 | `POST /images/generations` | OpenAI 兼容，`response_format: b64_json` |
| 包 | `uvx --from <wheel URL> seedream-image-mcp` | 模型名直通版 `4.2.0.post1`，从 GitHub Release 安装；不要用 PyPI 的 `seedream-image-mcp==4.2.0`（它会把别名展开成网关未登记的 raw ID） |
| Wheel URL | `https://github.com/wandouni/Seedream_MCP/releases/download/v4.2.0.post1/seedream_image_mcp-4.2.0.post1-py3-none-any.whl` | 公开可下载，MIT，源码分支 `gateway-passthrough` |
| 安装版本校验 | `seedream-image-mcp --version` → `4.2.0.post1` | 显示 `4.2.0` 说明用错了包 |
| 模型名 | `doubao-seedream-5.0-lite` | 网关 `/v1/models` 里唯一登记的 Seedream 条目；**不存在 raw ID `doubao-seedream-5-0-260128`，也无法加白** |
| 模型名直通 | `SEEDREAM_MODEL_PASSTHROUGH=true` | 让 `SEEDREAM_MODEL_ID` 原样进请求体，不查别名表。设 `false` 即恢复官方 4.2.0 行为 |
| MCP 服务名 | `seedream` | 三端必须同名，便于 cc-switch 矩阵和用户识别 |
| 环境变量 | `ARK_API_KEY`、`ARK_BASE_URL`、`SEEDREAM_MODEL_ID`、`SEEDREAM_MODEL_PASSTHROUGH`、`SEEDREAM_DEFAULT_SIZE`、`SEEDREAM_DEFAULT_WATERMARK`、`SEEDREAM_DATA_ROOT` | 仅这 7 个，勿自造 |
| 默认尺寸 | `2K` | 也可用 `3K`/`4K` 或 `2048x2048` 这类像素值 |
| 尺寸下限 | 3,686,400 像素（≈1920×1920） | 更小直接 `400 image size must be at least 3686400` |
| 图片落盘 | `<SEEDREAM_DATA_ROOT>/.seedream/images/<日期>/<工具名>/` | 默认根目录 `~/Pictures/Seedream` |
| 日志 | `<SEEDREAM_DATA_ROOT>/.seedream/logs/seedream_mcp.log` | 5MB 轮转、保留 7 天 |
| 暴露的工具 | `text_to_image`、`image_to_image`、`multi_image_fusion`、`sequential_generation`、`browse_images`、`get_model_info` | 握手验收要求至少含 `text_to_image` |
| uvx（macOS） | `~/.local/bin/uvx` | |
| uvx（Windows） | `%USERPROFILE%\.local\bin\uvx.exe` | |
| WorkBuddy 配置 | `~/.workbuddy/mcp.json` | Windows：`%USERPROFILE%\.workbuddy\mcp.json` |
| WorkBuddy 信任记录 | `~/.workbuddy/mcp-approvals.json` | 首次调用会弹确认 |
| cc-switch 数据库 | `~/.cc-switch/cc-switch.db` | 它的 MCP 矩阵会**按自己的库重写**上面两个文件 |

**关键约束**：

1. Claude Code / Codex 的主模型槽位只能放文本模型。生图必须走 MCP 工具，**不要把 `doubao-seedream-5.0-lite` 填进主模型/子模型配置**，那会导致 403 和整个会话失效。
2. 网关对模型名做精确匹配，大小写和分隔符都要照抄：`doubao-seedream-5.0-lite`（中间是点，不是横线；结尾是 `lite`，不是 `5-0-260128`）。

---

## 2. 执行顺序（决策树）

```
1. 确认 uvx 可用？ ── 否 → 安装 uv（§3.1），装完回到这里
2. 确认 Token 可用？ ── 否 → 问用户（§0），只问一次
3. 网关授权探测 ── 403 → 模型名不是网关登记的别名，检查 SEEDREAM_MODEL_ID（§3.4）
                ── 401 → base_url 漏了 /v1 或 Token 错
                ── 400 → 正常（尺寸探测被拒＝模型已被网关登记），继续
4. 判 cc-switch 是否存在（~/.cc-switch/cc-switch.db）
   ├─ 存在 → 跑脚本写文件（§3），然后在交付报告里要求用户去 cc-switch UI 同步（§4）
   └─ 不存在 → 跑脚本写文件（§3）
5. 握手验证（脚本内置）── ok=false → 查 §7
6. 交付报告（§10）
```

---

## 3. 主路径：运行仓库脚本

脚本：`scripts/setup_seedream_mcp.py`（路径相对 LangBot 仓库根；不在仓库内就问用户要仓库路径）。

### 3.1 前置：安装 uv（缺 uvx 时）

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```powershell
# Windows PowerShell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

装完预热一次，避免 MCP 首次启动从 GitHub 现下载安装包导致握手超时：

```bash
uvx --from https://github.com/wandouni/Seedream_MCP/releases/download/v4.2.0.post1/seedream_image_mcp-4.2.0.post1-py3-none-any.whl seedream-image-mcp --version
```

输出应为 `seedream-image-mcp 4.2.0.post1`。若下载失败（办公网屏蔽 GitHub），转 §8 的兜底方案。

### 3.2 先 dry-run，再落盘

```bash
# 只看计划，不写文件
python3 scripts/setup_seedream_mcp.py --dry-run

# 正式执行（Token 走环境变量，不要用 --token 明文）
ARK_API_KEY="$KEY" python3 scripts/setup_seedream_mcp.py
```

常用参数：

| 参数 | 用途 |
| --- | --- |
| `--targets claude,codex,workbuddy` | 只配指定端，默认三端全配 |
| `--home <path>` | 覆盖主目录（测试/非标准部署） |
| `--base-url <url>` | 换网关时用，默认 `https://ai.ctaigw.cn/v1` |
| `--model-id <id>` | 换模型，默认 `doubao-seedream-5.0-lite`；只有网关登记过的名字才通 |
| `--data-root <path>` | 图片落盘根目录 |
| `--force` | 覆盖 Codex 里**手工写的**同名段（会先备份，并删掉手工段避免 TOML 重复键） |
| `--skip-gateway-check` | 跳过网关探测（离线演习，别在正式流程用） |
| `--skip-handshake` | 跳过 MCP 握手（只在已知 uvx 慢启动时临时用，不能作为验收依据） |
| `--timeout 180` | 握手超时秒数 |

### 3.3 退出码语义（必须按码分支，不要只看文本）

| 码 | `status` | 含义 | 你的下一步 |
| --- | --- | --- | --- |
| 0 | `verified` | 写入成功且握手通过 | 交付（§10） |
| 0 | — | dry-run 且无异常 | 向用户报告将写哪些文件，等确认后去掉 `--dry-run` |
| 1 | `configured_unverified` | 文件写了，但握手失败 | 查 §7 的「握手失败」，修完重跑 |
| 1 | `write_failed` | 目标文件不是合法 JSON/TOML，或手工段冲突 | 按 `error` 字段处理；手工段冲突才用 `--force` |
| 2 | `prerequisite_missing` / `token_missing` | 缺 uvx 或 Token | 装 uv / 问用户要 Token |
| 3 | `gateway_blocked` | 网关不认这个模型名 | 按 `gateway.action` 把 `--model-id` 改成 `doubao-seedream-5.0-lite` 重跑（§3.4） |

报告里的关键字段：`writes.<target>.{path,changed,backup,created}`、`handshake.{ok,tools}`、`gateway.{ok,http_status,reason}`、`warning`。

**幂等性**：第二次运行应出现三个 `changed: false`，且不产生新备份。若 `changed: true` 反复出现，说明有外力在改写配置（通常是 cc-switch），见 §4。

### 3.4 `gateway_blocked` 时怎么修

`reason=model_not_authorized` 只有一个原因：`SEEDREAM_MODEL_ID` 不是网关登记的名字。按顺序检查：

1. 是否为 `doubao-seedream-5.0-lite`（点号、小写、结尾 `lite`）。
2. `SEEDREAM_MODEL_PASSTHROUGH` 是否被改成了 `false`——那样包会把别名展开成 raw ID `doubao-seedream-5-0-260128`，网关不认。
3. `args` 是否仍指向官方包（`seedream-image-mcp==4.2.0`），而不是 §1 的 wheel URL。

修好重跑脚本。**不要**建议用户去申请加白：网关管理员已明确不支持。

---

## 4. 分支：cc-switch 存在

cc-switch 的 MCP 矩阵行＝MCP、列＝应用（Claude Code / Codex），切换 provider 时会用 `~/.cc-switch/cc-switch.db` 的内容重写 `~/.claude.json` 与 `~/.codex/config.toml`。所以脚本写完可能被它覆盖。

**动作**：脚本报告里出现 `warning`（检测到 cc-switch）时，不要自己改数据库。在交付报告里给用户这段操作，并明确说「不做这步，切换 provider 后配置会消失」：

1. 打开 cc-switch → 左侧栏 **MCP** → **添加 MCP**
2. 「粘贴配置」贴入 §5.1 的 JSON（Windows 换成绝对路径版）
3. 勾选写入到 **Claude Code** 与 **Codex**
4. 回到 MCP 矩阵，把 `seedream` 行对应两列开关打开

WorkBuddy 不在 cc-switch 管理范围，脚本已直接写好，无需 UI 操作。

---

## 5. 兜底：手写配置（脚本不可用时）

### 5.1 macOS

```json
{
  "mcpServers": {
    "seedream": {
      "type": "stdio",
      "command": "/Users/<用户名>/.local/bin/uvx",
      "args": [
        "--from",
        "https://github.com/wandouni/Seedream_MCP/releases/download/v4.2.0.post1/seedream_image_mcp-4.2.0.post1-py3-none-any.whl",
        "seedream-image-mcp"
      ],
      "env": {
        "ARK_API_KEY": "<网关 Token>",
        "ARK_BASE_URL": "https://ai.ctaigw.cn/v1",
        "SEEDREAM_MODEL_ID": "doubao-seedream-5.0-lite",
        "SEEDREAM_MODEL_PASSTHROUGH": "true",
        "SEEDREAM_DEFAULT_SIZE": "2K",
        "SEEDREAM_DEFAULT_WATERMARK": "false",
        "SEEDREAM_DATA_ROOT": "/Users/<用户名>/Pictures/Seedream"
      }
    }
  }
}
```

### 5.2 Windows

只改 `command` 与数据目录两处（**必须绝对路径**，GUI 客户端读不到终端 PATH）：

```json
"command": "C:\\Users\\<用户名>\\.local\\bin\\uvx.exe"
```

```json
"SEEDREAM_DATA_ROOT": "C:\\Users\\<用户名>\\Pictures\\Seedream"
```

### 5.3 三端写入位置

| 客户端 | 位置 | 写法 |
| --- | --- | --- |
| Claude Code | `~/.claude.json` | 顶层 `mcpServers` 合并，**保留其他键** |
| Codex | `~/.codex/config.toml` | 追加 `[mcp_servers.seedream]` + `[mcp_servers.seedream.env]`，**同一服务不得出现两个 `[mcp_servers.seedream]` 段**（TOML 重复键会让整份文件失效） |
| WorkBuddy | `~/.workbuddy/mcp.json` | 整份就是 `{"mcpServers": {...}}` |

写之前必须备份（`<file>.bak-<时间戳>`）；文件不是合法 JSON/TOML 时**拒绝覆盖**，先报给用户。

---

## 6. 验收标准（缺一不可）

1. 三个目标文件都存在且含 `seedream` 条目。
2. 重启客户端后，MCP 工具列表里能看到 `text_to_image`（其余 5 个工具也应存在）。
3. 实际生成一张图，返回本地绝对路径，且文件确实存在、体积 > 0。
4. 复跑脚本得到 `changed: false`（配置稳定，没被外力重置）。
5. 若检测到 cc-switch，已提示用户做 UI 同步。

验收命令（macOS，避免打印 Token）：

```bash
ls -la ~/Pictures/Seedream/.seedream/images/$(date +%Y-%m-%d)/ 2>/dev/null
tail -20 ~/Pictures/Seedream/.seedream/logs/seedream_mcp.log
```

---

## 7. 错误 → 动作映射

| 现象 / 报错原文 | 原因 | 动作 |
| --- | --- | --- |
| `403 model_no_authorization` | 模型名不是网关登记的别名，或直通被关掉 | 按 §3.4 三项检查；`SEEDREAM_MODEL_ID=doubao-seedream-5.0-lite` 且 `SEEDREAM_MODEL_PASSTHROUGH=true` |
| `400 image size must be at least 3686400` | 尺寸太小 | 用 `2K` 或 `2048x2048` |
| `401 api-key access forbit` | `ARK_BASE_URL` 漏了 `/v1`，或 Token 无效 | 改 `https://ai.ctaigw.cn/v1`；重新核对 Token |
| `handshake.ok=false`，`reason=timeout` | 首次从 GitHub 下载安装包 / uvx 慢 / 网络 | 先跑 §3.1 的预热命令，再重跑脚本（提高 `--timeout`） |
| `handshake.ok=false`，`reason=spawn_failed` | uvx 拉不到 wheel（断网、GitHub 被屏蔽） | 转 §8 兜底方案 |
| `handshake.ok=false`，`tools=[]` | uvx 路径错（尤其 GUI 用了裸 `uvx`） | 改绝对路径；确认 `uvx` 版本可执行 |
| `tools` 有内容但不含 `text_to_image` | 装成了别的包/版本 | `args` 必须是 `["--from", "<wheel URL>", "seedream-image-mcp"]`；`--version` 应为 `4.2.0.post1` |
| Codex 报 TOML 解析错误 | 文件里有重复段 | 跑脚本不加 `--force` 应先被拒；若已损坏，从 `.bak-*` 恢复或加 `--force` 让脚本去重 |
| 工具列表里没有 `seedream` | 客户端没重启 / 配置写到了别的文件 | 重启客户端；核对 §5.3 路径 |
| 用户想把主模型改成生图模型 | 槽位不匹配 | 拒绝；主模型保持文本模型，生图只走 MCP |
| 消息里出现 `model_no_authorization` 但主模型是文本 | 会话里有子模型/小模型被填成生图模型 | 检查 cc-switch provider 里的各类模型字段 |

排查细节一律看 `<SEEDREAM_DATA_ROOT>/.seedream/logs/seedream_mcp.log`（错误含完整堆栈）。

---

## 8. 分支：GitHub 不可达 / 网关改用 raw ID

### 8.1 GitHub 下载不到 wheel

办公网屏蔽 GitHub 时，`uvx --from <URL>` 会卡住或报 `spawn_failed`。两个选择，按优先级：

1. **离线安装**：在能上网的机器上下载 wheel，拷到目标机器后
   `uv tool install --from ./seedream_image_mcp-4.2.0.post1-py3-none-any.whl seedream-image-mcp`，
   再把 MCP 的 `command` 写成该工具生成的绝对路径（`uv tool dir --bin` 下）。
2. **单文件兜底**：用附录 B 的脚本，只有 `generate_image` 一个工具，没有图生图/多图融合/组图/browse。这是最后手段，不要作为默认方案。

### 8.2 网关以后支持了 raw ID

不需要换回官方包。改两处并重跑脚本：

```bash
ARK_API_KEY="$KEY" python3 scripts/setup_seedream_mcp.py --model-id doubao-seedream-5-0-260128
```

再把三端配置里的 `SEEDREAM_MODEL_PASSTHROUGH` 改成 `false`（脚本固定写 `true`，这一步得手动改；此时包恢复官方语义，别名会被展开成 raw ID）。改完必须重新握手验证。

---

## 9. 提示词库（可直接粘贴使用）

### 9.1 粘贴给 AI 的一键安装提示词

```text
请按仓库文档 docs/豆包Seedream生图MCP接入指南-AI执行版.md 给我配置豆包 Seedream 生图 MCP。

要求：
1. 先跑 python3 scripts/setup_seedream_mcp.py --dry-run，把要写的文件和改动点告诉我，等我确认。
2. 网关 Token 从环境变量 ARK_API_KEY 读取；如果读不到，再从 ~/.claude/settings.json 的 env.ANTHROPIC_AUTH_TOKEN 读；都没有就问我。全程不要在命令行或回复里打印 Token。
3. 确认后正式执行，把 Claude Code、Codex、WorkBuddy 三端都配上。
4. 脚本退出码非 0 时，按文档 §3.3 和 §7 判断原因，告诉我具体错在哪一步、下一步该做什么，不要直接说"已配好"。
5. 最后按文档 §10 的格式给我交付报告，并提醒我重启客户端。
```

### 9.2 AI 必须向用户确认的最小问题集

只问缺的那几个，不要一次问全：

1. Token：能不能从 `ARK_API_KEY` 或 `~/.claude/settings.json` 读到？（读不到才问用户要）
2. 三端都要配，还是只配其中某几个？
3. 图片存哪个目录？（默认 `~/Pictures/Seedream`，够用就别问）
4. 能否访问 GitHub？（不能访问就走 §8.1 的离线安装或兜底脚本）

### 9.3 出图提示词模板

**文生图**

```text
用 seedream 的 text_to_image 生成一张图：
主体：<谁/什么>
场景：<在哪、什么时间、什么天气>
构图：<近景/中景/全景；主体位置>
风格：<写实摄影/电影感/扁平插画/水彩/3D 渲染>
光线与色调：<柔光/逆光/冷色调>
画幅：2K
负面要求：不要文字、不要水印、不要畸形手指
```

**图生图（改一张已有图）**

```text
用 image_to_image 处理这张图：<绝对路径或先让我 browse_images 找>
保留：<要保留的部分，如人物五官、服装版型、构图>
修改：<要改的部分，如换成夏装、背景改成海边、时间改成黄昏>
风格：<保持一致 / 转成某风格>
强度：<微调 / 明显改动但主体不变>
画幅：2K
```

**多图融合（必须用「图1/图2」指代，顺序即参数顺序）**

```text
用 multi_image_fusion 融合这两张图：
图1：<路径> —— 提供 <元素，如服装款式>
图2：<路径> —— 提供 <元素，如模特姿态与场景>
融合要求：<最终画面里两者的关系>
风格：<统一成什么风格>
画幅：2K
```

**组图 / 分镜（一次生成一组风格一致的图）**

```text
用 sequential_generation 生成一组 <N> 张连贯图片：
主题：<一句话>
统一设定：<人物外观、配色、风格、色温，必须每张都一致>
分镜：1) <描述> 2) <描述> 3) <描述>
画幅：2K
```

**找图 / 查能力**

```text
用 browse_images 列出 ~/Pictures/Seedream 下最近的 10 张图，返回绝对路径。
```

```text
用 get_model_info 告诉我当前模型的参考图上限、支持的尺寸档位，以及是否支持透明背景和 web_search。
```

### 9.4 让 AI 优化你的生图提示词

```text
你是 Seedream 生图提示词优化器。把我给的粗略想法改写成一个结构化中文提示词，输出仅包含以下字段，每项一行，不要解释：
主体 / 场景 / 构图 / 风格 / 光线与色调 / 画幅 / 负面要求
约束：
- 画幅固定写 2K（或我指定的像素值，必须 ≥ 3686400 像素）
- 风格词要具体（例如"85mm 人像镜头、浅景深、柔和自然光"，不要只写"好看"）
- 不要出现"高清""4K 画质""大师作品"这类无信息量的词
- 负面要求默认：不要文字、不要水印、不要畸形手指

我的想法：<一句话描述>
```

### 9.5 排错提示词

```text
seedream MCP 出图失败，请按 docs/豆包Seedream生图MCP接入指南-AI执行版.md §7 排查：
1. 先读 <SEEDREAM_DATA_ROOT>/.seedream/logs/seedream_mcp.log 最后 50 行；
2. 对照错误原文定位到 §7 表格里的某一行，告诉我命中哪一行；
3. 按该行的"动作"执行，不要跳过验证；
4. 如果需要改配置，改完必须重新握手验证，不能只看文件内容。

错误原文：<粘贴报错>
```

---

## 10. 交付报告格式（AI 输出给用户，照此填写）

```text
【Seedream 生图 MCP 配置结果】

结论：<已配好并验证 / 部分完成 / 失败：<一句话原因>>

平台：<macOS / Windows>
模型：<doubao-seedream-5.0-lite（直通版 4.2.0.post1）>
图片目录：<SEEDREAM_DATA_ROOT>

客户端             配置               状态
Claude Code       ~/.claude.json      <已写入 / 无变化 / 失败>
Codex             ~/.codex/config.toml  <已写入 / 无变化 / 失败>
WorkBuddy         ~/.workbuddy/mcp.json  <已写入 / 无变化 / 失败>

握手验证：<通过，工具 6 个 / 失败：<原因>>
备份文件：<路径 或 无>
网关授权：<已登记该模型名 / 未登记：<具体报错>>

你需要做的：
1. 重启 <Claude Code / Codex / WorkBuddy>
2. <若检测到 cc-switch：去 cc-switch 的 MCP 面板同步添加 seedream，否则切换 provider 后配置会被覆盖>
3. 说一句「用 seedream 生成一张测试图」验证

Token 未在任何回复、日志或仓库文件中出现。
```

---

## 附录 A：脚本能力摘要（便于判断该不该用它）

`scripts/setup_seedream_mcp.py` 做的事，与手写配置等价但更稳：

- 平台探测、`uvx` 绝对路径解析（含 `~/.local/bin`、`~/.cargo/bin` 兜底）
- Token 三级取值（`--token` → 环境变量 → `~/.claude/settings.json`）
- 网关探测：用非法尺寸 `1024x1024` 空转，`403` 判模型名未被登记、`400` 判模型名可用、`401` 判 Token/URL 错
- JSON 合并保留其余键；非 JSON 拒绝覆盖；Codex 用托管块标记（`# >>> seedream-mcp`）更新，去重同名段
- 真实 stdio 握手：`initialize` → `notifications/initialized` → `tools/list`（顺序交互，避免 EOF 丢包）
- 所有写入前备份为 `<file>.bak-<时间戳>`
- 输出机器可读 JSON，退出码对应 §3.3

---

## 附录 B：最后手段——直通网关的单文件 MCP

只在 §8.1 的两种情况用：GitHub 下载不到 wheel，且离线安装也走不通。不翻译别名，`DOUBAO_IMAGE_MODEL` 直接填网关认得的名字。

保存为 `~/mcp/doubao-image/server.py`，依赖由 `uv run --script` 按 PEP 723 自动安装：

```python
# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=1.2,<2"]
# ///
"""Minimal MCP server exposing Doubao Seedream image generation.

Works with any OpenAI-compatible ``POST /images/generations`` endpoint,
including Volcengine Ark and gateways that proxy it.

Environment:
    DOUBAO_IMAGE_API_KEY     required, bearer token
    DOUBAO_IMAGE_BASE_URL    default https://ark.cn-beijing.volces.com/api/v3
    DOUBAO_IMAGE_MODEL       default doubao-seedream-5.0-lite
    DOUBAO_IMAGE_OUTPUT_DIR  default ./generated-images
"""

import base64
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("doubao-image")

BASE_URL = os.environ.get("DOUBAO_IMAGE_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
MODEL = os.environ.get("DOUBAO_IMAGE_MODEL", "doubao-seedream-5.0-lite")
OUTPUT_DIR = Path(os.environ.get("DOUBAO_IMAGE_OUTPUT_DIR", "generated-images"))

# Seedream rejects images below 3686400 total pixels.
MIN_PIXELS = 3_686_400


def _generate(prompt: str, size: str, watermark: bool) -> Path:
    api_key = os.environ.get("DOUBAO_IMAGE_API_KEY")
    if not api_key:
        raise RuntimeError("DOUBAO_IMAGE_API_KEY is not set")

    try:
        width, height = (int(part) for part in size.lower().split("x"))
    except ValueError as exc:
        raise ValueError(f"size must look like 2048x2048, got {size!r}") from exc
    if width * height < MIN_PIXELS:
        raise ValueError(f"size {size} is too small; Seedream requires at least {MIN_PIXELS} pixels (e.g. 1920x1920)")

    body = json.dumps(
        {
            "model": MODEL,
            "prompt": prompt,
            "size": f"{width}x{height}",
            "response_format": "b64_json",
            "watermark": watermark,
        }
    ).encode()
    request = urllib.request.Request(
        f"{BASE_URL}/images/generations",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:800]
        raise RuntimeError(f"image generation failed: HTTP {exc.code} {detail}") from exc

    item = (payload.get("data") or [{}])[0]
    if not item.get("b64_json"):
        raise RuntimeError(f"image generation returned no b64_json: {str(payload)[:500]}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}"
    target = OUTPUT_DIR / f"{stamp}.jpeg"
    target.write_bytes(base64.b64decode(item["b64_json"]))
    return target.resolve()


@mcp.tool()
def generate_image(prompt: str, size: str = "2048x2048", watermark: bool = False) -> str:
    """Generate an image with Doubao Seedream and save it to disk.

    Args:
        prompt: Chinese or English description of the desired image.
        size: WxH in pixels, at least 3,686,400 total pixels. Default 2048x2048.
        watermark: Whether to add an "AI generated" watermark. Default False.
    """
    path = _generate(prompt, size, watermark)
    return f"Saved generated image to {path}"


if __name__ == "__main__":
    mcp.run()
```

对应的 MCP 条目（macOS；Windows 把 `command` 换成 `C:\\Users\\<用户名>\\.local\\bin\\uv.exe`，脚本路径换成 Windows 路径）：

```json
{
  "mcpServers": {
    "doubao-image": {
      "type": "stdio",
      "command": "/Users/<用户名>/.local/bin/uv",
      "args": ["run", "--script", "/Users/<用户名>/mcp/doubao-image/server.py"],
      "env": {
        "DOUBAO_IMAGE_API_KEY": "<网关 Token>",
        "DOUBAO_IMAGE_BASE_URL": "https://ai.ctaigw.cn/v1",
        "DOUBAO_IMAGE_MODEL": "doubao-seedream-5.0-lite",
        "DOUBAO_IMAGE_OUTPUT_DIR": "/Users/<用户名>/Pictures/Seedream"
      }
    }
  }
}
```

这条方案只暴露 `generate_image`，没有图生图/多图融合/组图/browse 能力；能装上直通版后应改回 `seedream`。
