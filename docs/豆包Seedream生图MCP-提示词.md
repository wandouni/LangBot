# 豆包 Seedream 生图 MCP：给同事直接复制的提示词

同事不会配 MCP，也不该去配。这份文档的用法是：**让对方把下面某一段整段复制，发给自己的 AI**（Claude Code、WorkBuddy 里自带的 AI、或者任何能操作本机的 AI 助手），AI 就会自己装包、写配置、并真实生成一张图来证明配好了，最后给出可以直接复制的示例提问。

不需要仓库、不需要懂 JSON，也不需要给对方讲原理。选错环境的后果是配置写到了不存在的文件里，所以第一步是让对方按「我在用哪个客户端」选一段。

配套材料：

- 人工阅读版：[豆包Seedream生图MCP接入指南.md](./豆包Seedream生图MCP接入指南.md)
- AI 执行版（英文事实表、错误映射齐全）：[豆包Seedream生图MCP接入指南-AI执行版.md](./豆包Seedream生图MCP接入指南-AI执行版.md)

---

## 第 0 步：先问清楚，再给提示词

| 同事的情况                          | 给哪一段                                                |
| ----------------------------------- | ------------------------------------------------------- |
| 只用 Claude Code                    | [提示词 1](#提示词-1只配-claude-code推荐首次使用)        |
| 只用 Codex                          | [提示词 2](#提示词-2只配-codex)                          |
| Claude Code + Codex，装了 cc-switch | [提示词 3](#提示词-3claude-code--codex用-cc-switch-管理) |
| 只用 WorkBuddy（Windows 或 macOS）  | [提示词 4](#提示词-4只用-workbuddywindows--macos-通用)   |
| 三端都要                            | [提示词 5](#提示词-5三端全配)                            |

提示词 1–5 末尾都已内置「GitHub 打不开」和「装包失败」的备选方案，同事不需要再另外追加片段。

配置里的 `seedream` 是**服务名**（`mcpServers.seedream`），不是工具名。工具本身叫 `text_to_image`，客户端给模型看的完整名是 `mcp__<服务名>__<工具名>`，即 **`mcp__seedream__text_to_image`**；工具列表和日志里看到的应该都是这个全名。

不用问对方「你的 base_url 是什么」「模型 ID 是什么」——这些是固定事实，已经写进提示词，**不要让同事自己填**。填错模型名或装错包的表现都是「工具都在，但一画图就 403 `model_no_authorization`」，提示词里已经把正确值写死了，同事不需要、也不该改。

**提示词里没有任何需要同事替换的占位符**：Token 由 AI 自己从环境变量或 `~/.claude/settings.json` 读取，读不到才会反问；文中出现的 `<用户名>`、`<时间戳>`、`<安装包地址>` 都是给 AI 的说明，同事原样复制即可，不需要动手改。

**每段提示词都强制 AI 在最后输出「还需要你做的」清单和「配置好后怎么问我」示例提问**，而且要求逐条列清「在哪点、点什么、勾什么、点完看到什么」。原因很实际：MCP 配置里有几步（重启客户端、cc-switch 导入、WorkBuddy 首次授权）**只有人能完成**，AI 写得再对，用户不知道要做这几步，最后表现仍然是「配好了但不能用」。

收到 AI 的回复后，用这张表验收：

| 检查项                                                    | 合格                                                                           |
| --------------------------------------------------------- | ------------------------------------------------------------------------------ |
| 有没有单独一段「还需要你做的」                            | 有，且是编号列表；不是藏在正文里的一句「记得重启」                             |
| 有没有给「配置好后怎么问我」                              | 有，示例提问带工具名、要求贴本地路径；不是只让同事说「画张图」                 |
| 有没有说重启哪个客户端、怎么算真退出                      | 有（关进程，不是最小化窗口）                                                   |
| 用的是 WorkBuddy 的话，有没有列「连接器」里启用           | 有，写清打开 WorkBuddy → 连接器 → 打开 seedream 开关；只写重启不算           |
| 用的是 WorkBuddy 的话，有没有教你怎么确认不是内置模型画的 | 有，要求看 `<图片目录>/.seedream/images/` 下有没有新增文件，并给出工具完整名 |
| 装了 cc-switch 的话，有没有列「从应用导入」               | 有，写清勾选 seedream + Claude Code + Codex                                    |
| 验证结果是不是具体数字                                    | 有工具个数、图片路径、文件大小，而不是「应该可以了」                           |
| 失败时有没有给原始报错                                    | 有，且指出卡在第几步                                                           |

配好之后怎么问，提示词里已经要求 AI 在最终结论中列成【配置好后怎么问我】，把示例提问原样给同事即可。**不要只说「画张图」**——含糊说法会让助手用内置能力应付，看着有图，其实根本没走 seedream。

---

## 提示词 1：只配 Claude Code（推荐首次使用）

```text
帮我在这台电脑上配一个「AI 生图」工具，让我在 Claude Code 里可以直接说「画一张图」。

背景（这些是已经确认好的事实，请不要改、不要猜别的值）：
- 网关地址：https://ai.ctaigw.cn/v1（必须带 /v1）
- 模型名：doubao-seedream-5.0-lite（中间是点，结尾是 lite，不要改成带日期的那种名字）
- 安装包下载地址：
  https://github.com/wandouni/Seedream_MCP/releases/download/v4.2.0.post1/seedream_image_mcp-4.2.0.post1-py3-none-any.whl
- 这个包要求 Python 3.12+，用 uvx 启动即可，不需要我手动装 Python

请你做这几件事：

1. 检查 uv/uvx 是否已安装（命令 uvx --version）。没装就按系统安装：
   macOS: curl -LsSf https://astral.sh/uv/install.sh | sh
   Windows: powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   然后预热一次（可能要下载几十 MB，耐心等）：
   uvx --from <上面那个下载地址> seedream-image-mcp --version
   必须看到 4.2.0.post1 才算成功。

2. 找我的网关 Token，顺序是：
   a) 环境变量 ARK_API_KEY 或 SEEDREAM_API_KEY
   b) ~/.claude/settings.json 里的 env.ANTHROPIC_AUTH_TOKEN
   都找不到就问我一次。找到后把真实值填进下文的 ARK_API_KEY（填 Token 本身，不要填说明文字或占位符）。Token 只能写进配置文件，绝对不要在回复里、命令里打印出来。

3. 把下面这条服务合并进 ~/.claude.json 的 mcpServers（只加 seedream 这一条，其他设置原样保留；改之前先备份成 ~/.claude.json.bak-<时间戳>）：
   - 服务名：seedream
   - 启动命令：uvx 的绝对路径（用 which uvx 或 where uvx 拿到；GUI 环境读不到 PATH）
   - 参数：["--from", "<上面那个下载地址>", "seedream-image-mcp"]
   - 环境变量：
     ARK_API_KEY=（Token 由你按第 2 步找到后原样填入，不要在这里保留占位符）
     ARK_BASE_URL=https://ai.ctaigw.cn/v1
     SEEDREAM_MODEL_ID=doubao-seedream-5.0-lite
     SEEDREAM_MODEL_PASSTHROUGH=true
     SEEDREAM_DEFAULT_SIZE=2K
     SEEDREAM_DEFAULT_WATERMARK=false
     SEEDREAM_DATA_ROOT=~/Pictures/Seedream
   Windows 上数据目录写成 C:\Users\<用户名>\Pictures\Seedream，uvx 写成 C:\Users\<用户名>\.local\bin\uvx.exe。

4. 验证，不能只看配置文件就算完：
   a) 用 stdio 方式真实启动这个 MCP（initialize -> notifications/initialized -> tools/list），确认能列出 6 个工具，且包含 text_to_image；
   b) 真实调用一次 text_to_image（提示词随便，比如「一只橘猫在窗台上晒太阳」），确认返回本地文件路径、文件存在且大小大于 0；
   c) 把生成的图片路径告诉我。

5. 如果任何一步失败，不要把结论写成「已配置好」。告诉我：卡在第几步、原始报错、以及你判断的原因。

网络或安装包失败时的备选方案（严格按顺序判断，不要一报错就跳到最后）：
a) 如果 uvx 从 GitHub 下载安装包卡住、超时或报错（公司网络打不开 GitHub）：
   - 告诉我需要哪个文件（seedream_image_mcp-4.2.0.post1-py3-none-any.whl），我从别处拷来放到指定目录；
   - 拿到本地文件后执行 uv tool install --from <本地文件路径> seedream-image-mcp；
   - 用 uv tool dir --bin 找到装好的可执行文件绝对路径，把 MCP 的启动命令改成它（参数留空，不再需要 --from）；
   - 其余配置和验证步骤不变。
   不要自己找镜像站下载，也不要改用 PyPI 上的 seedream-image-mcp==4.2.0（那个版本在这台网关会报 403）。
b) 只有 a) 也失败，并且你先说明原因、我明确回复「用兜底方案」之后，才执行单文件兜底：
   - 在本机建 ~/mcp/doubao-image/server.py，用 uv run --script 启动；
   - 只暴露一个 generate_image 工具，直接 POST https://ai.ctaigw.cn/v1/images/generations，参数：model=doubao-seedream-5.0-lite、response_format=b64_json、size 至少 1920x1920（总像素 ≥ 3686400，否则 400）；
   - 把结果保存为本地 jpeg 并返回绝对路径；配置写进 MCP 配置后同样要真实生成一张图验证；
   - 兜底版没有图生图、多图融合、组图、图片浏览能力，tools/list 只有 1 个工具，验收标准相应变成「generate_image 能真实出图」；必须在结论里写明这是兜底版，网络恢复后要换回正式版。
不要因为一次报错就默认用兜底版交差，也不要跳过 a) 直接写脚本。

这段提示词里没有需要我手动替换的内容，Token 也不用我填，你按第 2 步自己找就行。

最后必须按下面的格式给我结论，不要只回一句「已配好」：

【已完成】
- 装了哪个版本、改了哪个文件（写完整路径）、备份文件在哪

【验证结果】
- 握手拿到的工具个数；真实生成图片的完整路径和文件大小
- 任何一步没通过，写清卡在第几步、原始报错原文

【还需要你做的】（这些只有我能做，请一条一条列清楚，不要说「可选」）
1. 完全退出并重新打开 Claude Code（关闭进程，不是最小化窗口）
2. 用带完整工具名的问法验证一次，例如「用 mcp__seedream__text_to_image 画一只橘猫在窗台上晒太阳，并把本地图片路径贴给我」，不要只说「画张图」

【做完之后你会看到】
- 工具列表里出现 6 个工具；画图会返回一个本地图片路径

【配置好后怎么问我】（必须列出，方便我直接复制；不要只教我说「画张图」）
下面的指令每条都独立完整，可直接复制；不要用「同上」「通用」之类的指代。
1. 文生图：
   用 mcp__seedream__text_to_image 画一张图，并把工具返回的本地图片绝对路径原样贴给我：一只橘猫在午后的窗台上晒太阳，写实摄影，柔和侧光，2K，不要文字和水印。
2. 图生图：
   先用 mcp__seedream__browse_images 找到我最近生成的那张图，再用 mcp__seedream__image_to_image 把光线改成黄昏逆光，主体和构图不变，2K，并把工具返回的本地图片绝对路径贴给我。
3. 组图：
   用 mcp__seedream__sequential_generation 生成一组 4 张连贯画面：同一只橘猫从打哈欠到睡着，风格统一，2K，并把工具返回的本地图片绝对路径贴给我。
4. 多图融合：
   用 mcp__seedream__multi_image_fusion 把我最近两张图（一张猫、一张窗台）合成一张，写实风格，2K，并把工具返回的本地图片绝对路径贴给我。
5. 没走 seedream 时：
   刚才那次没有调用 seedream MCP，请直接调用 mcp__seedream__text_to_image 重画一次，不要用内置图片能力或文字描述代替，并把工具的原始返回贴给我。
如果你实际看到的完整工具名与示例不同，按实际名字写。
```

---

## 提示词 2：只配 Codex

```text
帮我在这台电脑上配一个「AI 生图」工具，让我在 Codex 里可以直接说「画一张图」。

背景（这些是已经确认好的事实，请不要改、不要猜别的值）：
- 网关地址：https://ai.ctaigw.cn/v1（必须带 /v1）
- 模型名：doubao-seedream-5.0-lite（中间是点，结尾是 lite，不要改成带日期的那种名字）
- 安装包下载地址：
  https://github.com/wandouni/Seedream_MCP/releases/download/v4.2.0.post1/seedream_image_mcp-4.2.0.post1-py3-none-any.whl
- 这个包要求 Python 3.12+，用 uvx 启动即可，不需要我手动装 Python

请你做这几件事：

1. 检查 uv/uvx 是否已安装（命令 uvx --version）。没装就按系统安装：
   macOS: curl -LsSf https://astral.sh/uv/install.sh | sh
   Windows: powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   然后预热一次（可能要下载几十 MB，耐心等）：
   uvx --from <上面那个下载地址> seedream-image-mcp --version
   必须看到 4.2.0.post1 才算成功。

2. 找我的网关 Token，顺序是：
   a) 环境变量 ARK_API_KEY 或 SEEDREAM_API_KEY
   b) ~/.claude/settings.json 里的 env.ANTHROPIC_AUTH_TOKEN
   都找不到就问我一次。找到后把真实值填进下文的 ARK_API_KEY（填 Token 本身，不要填说明文字或占位符）。Token 只能写进配置文件，绝对不要在回复里、命令里打印出来。

3. 写 Codex 的配置文件：macOS 是 ~/.codex/config.toml，Windows 是 %USERPROFILE%\.codex\config.toml。
   先备份成 config.toml.bak-<时间戳>，然后加入这两段：

   [mcp_servers.seedream]
   command = "<uvx 的绝对路径>"
   args = ["--from", "<上面那个下载地址>", "seedream-image-mcp"]

   [mcp_servers.seedream.env]
   ARK_API_KEY = "<Token>"
   ARK_BASE_URL = "https://ai.ctaigw.cn/v1"
   SEEDREAM_MODEL_ID = "doubao-seedream-5.0-lite"
   SEEDREAM_MODEL_PASSTHROUGH = "true"
   SEEDREAM_DEFAULT_SIZE = "2K"
   SEEDREAM_DEFAULT_WATERMARK = "false"
   SEEDREAM_DATA_ROOT = "~/Pictures/Seedream"
   （Windows 把这条改成 "C:\\Users\\<用户名>\\Pictures\\Seedream"）

   硬性规则：
   - 整份文件里只能有一份 [mcp_servers.seedream]。如果已经有同名段，把旧段整段替换掉，不要两份并列——TOML 里重复的表会让 Codex 判定整份配置无效，我原来的模型设置会一起失效。
   - 除了 seedream 相关的段，config.toml 里其他内容（model、provider、其他 mcp_servers）一个字都不要动。
   - 文件原本就不是合法 TOML 时不要覆盖，先告诉我哪里坏了。
   - command 必须写绝对路径（which uvx / where uvx 取），不要写裸 uvx。

4. 验证，不能只看配置文件就算完：
   a) 用 stdio 方式真实启动这个 MCP（initialize -> notifications/initialized -> tools/list），确认能列出 6 个工具，且包含 text_to_image；
   b) 真实调用一次 text_to_image（比如「一只橘猫在窗台上晒太阳」），确认返回本地文件路径、文件存在且大小大于 0；
   c) 把生成的图片路径告诉我。

5. 检查我是否装了 cc-switch（看 ~/.cc-switch/cc-switch.db 是否存在）。装了的话，它切换 provider 时会用自己数据库里的 MCP 列表覆盖 ~/.codex/config.toml，我现在写进去的配置会丢。你不用等我，也不要改 cc-switch 的数据库、不要用 ccswitch:// 深链接（Token 会进 URL），把「去 cc-switch 点一次从应用导入」作为结论里【还需要你做的】第 1 条告诉我。

6. 如果任何一步失败，不要把结论写成「已配置好」。告诉我：卡在第几步、原始报错、以及你判断的原因。

网络或安装包失败时的备选方案（严格按顺序判断，不要一报错就跳到最后）：
a) 如果 uvx 从 GitHub 下载安装包卡住、超时或报错（公司网络打不开 GitHub）：
   - 告诉我需要哪个文件（seedream_image_mcp-4.2.0.post1-py3-none-any.whl），我从别处拷来放到指定目录；
   - 拿到本地文件后执行 uv tool install --from <本地文件路径> seedream-image-mcp；
   - 用 uv tool dir --bin 找到装好的可执行文件绝对路径，把 MCP 的启动命令改成它（参数留空，不再需要 --from）；
   - 其余配置和验证步骤不变。
   不要自己找镜像站下载，也不要改用 PyPI 上的 seedream-image-mcp==4.2.0（那个版本在这台网关会报 403）。
b) 只有 a) 也失败，并且你先说明原因、我明确回复「用兜底方案」之后，才执行单文件兜底：
   - 在本机建 ~/mcp/doubao-image/server.py，用 uv run --script 启动；
   - 只暴露一个 generate_image 工具，直接 POST https://ai.ctaigw.cn/v1/images/generations，参数：model=doubao-seedream-5.0-lite、response_format=b64_json、size 至少 1920x1920（总像素 ≥ 3686400，否则 400）；
   - 把结果保存为本地 jpeg 并返回绝对路径；配置写进 MCP 配置后同样要真实生成一张图验证；
   - 兜底版没有图生图、多图融合、组图、图片浏览能力，tools/list 只有 1 个工具，验收标准相应变成「generate_image 能真实出图」；必须在结论里写明这是兜底版，网络恢复后要换回正式版。
不要因为一次报错就默认用兜底版交差，也不要跳过 a) 直接写脚本。

这段提示词里没有需要我手动替换的内容，Token 也不用我填，你按第 2 步自己找就行。

最后必须按下面的格式给我结论，不要只回一句「已配好」：

【已完成】
- 装了哪个版本、改了哪个文件（写完整路径）、备份文件在哪
- 你是怎么保证 config.toml 里只有一份 [mcp_servers.seedream] 的

【验证结果】
- 握手拿到的工具个数；真实生成图片的完整路径和文件大小
- 任何一步没通过，写清卡在第几步、原始报错原文

【还需要你做的】（这些只有我能做，请按顺序一条一条列清楚，不要说「可选」）
1. 如果检测到 cc-switch：打开 cc-switch → 左侧 MCP → 点「从应用导入」→ 勾选 seedream 和 Codex → 确认
2. 完全退出并重新打开 Codex（关闭进程，不是最小化窗口）
3. 在 Codex 里用带完整工具名的问法验证一次，例如「用 mcp__seedream__text_to_image 画一只橘猫在窗台上晒太阳，并把本地图片路径贴给我」，不要只说「画张图」

【做完之后你会看到】
- 工具列表里出现 6 个工具；画图会返回一个本地图片路径；装了 cc-switch 的话，它的 MCP 列表里有 seedream 且 Codex 开关打开

【配置好后怎么问我】（必须列出，方便我直接复制；不要只教我说「画张图」）
下面的指令每条都独立完整，可直接复制；不要用「同上」「通用」之类的指代。
1. 文生图（cc-switch 导入完成后第一句就发这个，兼做验收）：
   用 mcp__seedream__text_to_image 画一张图，并把工具返回的本地图片绝对路径原样贴给我：一只橘猫在午后的窗台上晒太阳，写实摄影，柔和侧光，2K，不要文字和水印。
2. 图生图：
   先用 mcp__seedream__browse_images 找到我最近生成的那张图，再用 mcp__seedream__image_to_image 把光线改成黄昏逆光，主体和构图不变，2K，并把工具返回的本地图片绝对路径贴给我。
3. 组图：
   用 mcp__seedream__sequential_generation 生成一组 4 张连贯画面：同一只橘猫从打哈欠到睡着，风格统一，2K，并把工具返回的本地图片绝对路径贴给我。
4. 多图融合：
   用 mcp__seedream__multi_image_fusion 把我最近两张图（一张猫、一张窗台）合成一张，写实风格，2K，并把工具返回的本地图片绝对路径贴给我。
5. 没走 seedream 时：
   刚才那次没有调用 seedream MCP，请直接调用 mcp__seedream__text_to_image 重画一次，不要用内置图片能力或文字描述代替，并把工具的原始返回贴给我。
如果你实际看到的完整工具名与示例不同，按实际名字写。
```

---

## 提示词 3：Claude Code + Codex，用 cc-switch 管理

```text
帮我把「AI 生图」工具同时配到 Claude Code 和 Codex 里，我的 MCP 是用 cc-switch 统一管理的。

已经确认的事实（请照抄，不要改）：
- 网关：https://ai.ctaigw.cn/v1
- 模型名：doubao-seedream-5.0-lite
- 安装包：
  https://github.com/wandouni/Seedream_MCP/releases/download/v4.2.0.post1/seedream_image_mcp-4.2.0.post1-py3-none-any.whl

配置内容如下（两边完全一样，只是写的位置不同）：

  服务名：seedream
  启动命令：uvx 的绝对路径（which uvx / where uvx 取得）
  参数：["--from", "<上面那个安装包地址>", "seedream-image-mcp"]
  环境变量：
    ARK_API_KEY=（Token 由你按第 2 步找到后原样填入，不要在这里保留占位符）
    ARK_BASE_URL=https://ai.ctaigw.cn/v1
    SEEDREAM_MODEL_ID=doubao-seedream-5.0-lite
    SEEDREAM_MODEL_PASSTHROUGH=true
    SEEDREAM_DEFAULT_SIZE=2K
    SEEDREAM_DEFAULT_WATERMARK=false
    SEEDREAM_DATA_ROOT=~/Pictures/Seedream

步骤：

1. uvx --version 确认已装 uv；没装就装，并跑一次
   uvx --from <安装包地址> seedream-image-mcp --version，看到 4.2.0.post1 再继续。
2. 找 Token：先看环境变量 ARK_API_KEY / SEEDREAM_API_KEY，再看 ~/.claude/settings.json 的 env.ANTHROPIC_AUTH_TOKEN，都没有就问我一次。找到后把真实值填进 ARK_API_KEY（填 Token 本身，不要填说明文字或占位符）。任何情况下不要把 Token 打印出来。
3. 写入两个文件（各自先备份成 .bak-<时间戳>）：
   - ~/.claude.json 的 mcpServers.seedream（保留其它内容）
   - ~/.codex/config.toml 追加 [mcp_servers.seedream] 和 [mcp_servers.seedream.env]（注意：同一节不能出现两次，否则整份文件失效）
4. 我在用 cc-switch，它会用自己数据库（~/.cc-switch/cc-switch.db 的 mcp_servers 表）里的内容覆盖上面两个文件，所以最后还差一步，这一步 cc-switch 没提供命令行，只能我手动点（只需点一次）。你不用等我，也不要尝试改 cc-switch 的数据库、不要用 ccswitch:// 深链接（Token 会进 URL），把这一步作为最终结论里「还需要你做的」第 1 条告诉我，并说明具体怎么点：
   - 先确认 seedream 已经写进 ~/.claude.json 和 ~/.codex/config.toml；
   - 我打开 cc-switch，进入左侧 MCP 页面，点「从应用导入」，确认框里应该列出 seedream，勾选 Claude Code 和 Codex，确认导入；
   - 导入后 cc-switch 的 MCP 列表里会出现 seedream，两个应用的开关是打开状态，以后再切 provider 也不会丢。
   如果「从应用导入」里看不到 seedream，就改成「添加 MCP -> 粘贴配置」，这时请把可粘贴的 JSON 给我。
5. 验证：用 stdio 真实启动服务，确认 tools/list 里有 6 个工具（含 text_to_image），并真实生成一张图，告诉我文件路径和大小。
6. 任何一步失败，如实说卡在哪、报什么错，不要写「已完成」。

网络或安装包失败时的备选方案（严格按顺序判断，不要一报错就跳到最后）：
a) 如果 uvx 从 GitHub 下载安装包卡住、超时或报错（公司网络打不开 GitHub）：
   - 告诉我需要哪个文件（seedream_image_mcp-4.2.0.post1-py3-none-any.whl），我从别处拷来放到指定目录；
   - 拿到本地文件后执行 uv tool install --from <本地文件路径> seedream-image-mcp；
   - 用 uv tool dir --bin 找到装好的可执行文件绝对路径，把 MCP 的启动命令改成它（参数留空，不再需要 --from）；
   - 其余配置和验证步骤不变。
   不要自己找镜像站下载，也不要改用 PyPI 上的 seedream-image-mcp==4.2.0（那个版本在这台网关会报 403）。
b) 只有 a) 也失败，并且你先说明原因、我明确回复「用兜底方案」之后，才执行单文件兜底：
   - 在本机建 ~/mcp/doubao-image/server.py，用 uv run --script 启动；
   - 只暴露一个 generate_image 工具，直接 POST https://ai.ctaigw.cn/v1/images/generations，参数：model=doubao-seedream-5.0-lite、response_format=b64_json、size 至少 1920x1920（总像素 ≥ 3686400，否则 400）；
   - 把结果保存为本地 jpeg 并返回绝对路径；配置写进 MCP 配置后同样要真实生成一张图验证；
   - 兜底版没有图生图、多图融合、组图、图片浏览能力，tools/list 只有 1 个工具，验收标准相应变成「generate_image 能真实出图」；必须在结论里写明这是兜底版，网络恢复后要换回正式版。
不要因为一次报错就默认用兜底版交差，也不要跳过 a) 直接写脚本。

这段提示词里没有需要我手动替换的内容，Token 也不用我填，你按第 2 步自己找就行。

最后必须按下面的格式给我结论，不要只回一句「已配好」：

【已完成】
- 装了哪个版本、改了哪两个文件（写完整路径）、备份文件在哪

【验证结果】
- 握手拿到的工具个数；真实生成图片的完整路径和文件大小
- 任何一步没通过，写清卡在第几步、原始报错原文

【还需要你做的】（这些只有我能做，请按顺序一条一条列清楚，不要说「可选」）
1. 打开 cc-switch → 左侧 MCP → 点「从应用导入」→ 确认框里勾选 seedream、**Claude Code**、**Codex** → 确认
2. 完全退出并重新打开 Claude Code 和 Codex（关闭进程，不是最小化窗口）
3. 分别在 Claude Code 和 Codex 里用带完整工具名的问法各验证一次，例如「用 mcp__seedream__text_to_image 画一只橘猫，并把本地图片路径贴给我」，不要只说「画张图」

【为什么要做第 1 步】
cc-switch 用自己数据库里的 MCP 列表覆盖这两个配置文件，不导入的话下次切 provider 就会丢。

【做完之后你会看到】
- cc-switch 的 MCP 列表里出现 seedream，两个应用的开关是打开的；两个客户端都能画图

【配置好后怎么问我】（必须按客户端分别列出，两个客户端各一组；每条指令都要能直接复制，不要用「同上」「通用」之类的指代；不要只教我说「画张图」）
1. 在 Claude Code 里发（文生图，兼做验收）：
   用 mcp__seedream__text_to_image 画一张图，并把工具返回的本地图片绝对路径原样贴给我：一只橘猫在午后的窗台上晒太阳，写实摄影，柔和侧光，2K，不要文字和水印。
2. 在 Codex 里发（文生图，兼做验收）：
   用 mcp__seedream__text_to_image 画一张图，并把工具返回的本地图片绝对路径原样贴给我：一只橘猫在午后的窗台上晒太阳，写实摄影，柔和侧光，2K，不要文字和水印。
3. 在 Claude Code 里发（图生图）：
   先用 mcp__seedream__browse_images 找到我最近生成的那张图，再用 mcp__seedream__image_to_image 把光线改成黄昏逆光，主体和构图不变，2K，并把工具返回的本地图片绝对路径贴给我。
4. 在 Codex 里发（图生图）：
   先用 mcp__seedream__browse_images 找到我最近生成的那张图，再用 mcp__seedream__image_to_image 把光线改成黄昏逆光，主体和构图不变，2K，并把工具返回的本地图片绝对路径贴给我。
5. 在 Claude Code 里发（组图或多图融合）：
   用 mcp__seedream__sequential_generation 生成一组 4 张连贯画面：同一只橘猫从打哈欠到睡着，风格统一，2K；或者用 mcp__seedream__multi_image_fusion 把我最近两张图（一张猫、一张窗台）合成一张。两种任选一种，并把工具返回的本地图片绝对路径贴给我。
6. 在 Codex 里发（组图或多图融合）：
   用 mcp__seedream__sequential_generation 生成一组 4 张连贯画面：同一只橘猫从打哈欠到睡着，风格统一，2K；或者用 mcp__seedream__multi_image_fusion 把我最近两张图（一张猫、一张窗台）合成一张。两种任选一种，并把工具返回的本地图片绝对路径贴给我。
7. 哪个客户端没走 seedream，就把这句发到那个客户端：
   刚才那次没有调用 seedream MCP，请直接调用 mcp__seedream__text_to_image 重画一次，不要用内置图片能力代替，并把工具的原始返回贴给我。
如果某端实际工具名与示例不同，按该端工具列表里的完整名替换后再发。
```

---

## 提示词 4：只用 WorkBuddy（Windows / macOS 通用）

```text
帮我在 WorkBuddy 里配一个「AI 生图」工具。

已经确认的事实（照抄，别改）：
- 网关：https://ai.ctaigw.cn/v1
- 模型名：doubao-seedream-5.0-lite
- 安装包：
  https://github.com/wandouni/Seedream_MCP/releases/download/v4.2.0.post1/seedream_image_mcp-4.2.0.post1-py3-none-any.whl

配置（下面标了 macOS 和 Windows 两种写法，请按我这台机器的系统选一种，不要两种混用）：
  服务名：seedream
  启动命令：uvx 的绝对路径 —— WorkBuddy 是 GUI 应用，读不到终端 PATH，必须写绝对路径
    macOS:   /Users/<用户名>/.local/bin/uvx
    Windows: C:\Users\<用户名>\.local\bin\uvx.exe
  参数：["--from", "<上面那个安装包地址>", "seedream-image-mcp"]
  环境变量：
    ARK_API_KEY=（Token 由你按第 2 步找到后原样填入，不要在这里保留占位符）
    ARK_BASE_URL=https://ai.ctaigw.cn/v1
    SEEDREAM_MODEL_ID=doubao-seedream-5.0-lite
    SEEDREAM_MODEL_PASSTHROUGH=true
    SEEDREAM_DEFAULT_SIZE=2K
    SEEDREAM_DEFAULT_WATERMARK=false
    SEEDREAM_DATA_ROOT=~/Pictures/Seedream          ← macOS
    SEEDREAM_DATA_ROOT=C:\Users\<用户名>\Pictures\Seedream   ← Windows（两种只取一种）

步骤：

1. 先确认我是什么系统，然后检查 uvx 是否存在：
   - macOS 看 /Users/<用户名>/.local/bin/uvx
   - Windows 看 %USERPROFILE%\.local\bin\uvx.exe
   没有就安装 uv：
   macOS:   curl -LsSf https://astral.sh/uv/install.sh | sh
   Windows: powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   装完预热一次（会下载几十 MB，耐心等）：
   uvx --from <安装包地址> seedream-image-mcp --version
   必须显示 4.2.0.post1。
2. 找 Token：环境变量 ARK_API_KEY / SEEDREAM_API_KEY，或 ~/.claude/settings.json 的 env.ANTHROPIC_AUTH_TOKEN；都没有就问我一次。找到后把真实值填进 ARK_API_KEY（填 Token 本身，不要填说明文字或占位符）。不要打印 Token。
3. 写入 WorkBuddy 的配置文件（文件不存在就新建，存在就先备份成 .bak-<时间戳>）：
   - macOS:   ~/.workbuddy/mcp.json
   - Windows: %USERPROFILE%\.workbuddy\mcp.json
   格式是：
   {"mcpServers": {"seedream": {"type": "stdio", "command": "...", "args": [...], "env": {...}}}}
   注意：Windows 上 JSON 里的路径反斜杠要写成双反斜杠（C:\\Users\\...）；macOS 直接用正斜杠。
   重要：WorkBuddy 不会自动启用新写进去的 MCP，光有配置文件、工具列表里也不会出现。必须由我打开 WorkBuddy 的「连接器」页面把它打开，这一步只能在图形界面里点，你替我点不了——所以请在最后的【还需要你做的】里单独列一条。
4. 验证：用 stdio 真实启动服务，确认 tools/list 有 6 个工具（含 text_to_image），并真实生成一张图，把图片路径和文件大小告诉我。
5. 注意 WorkBuddy 自带图片模型：配好 MCP 只是让它「多了一个可选工具」，我随口说一句「画张图」，助手完全可能用自带的模型应付，而且看起来一样成功——有图、有回复，只有翻产物目录才发现不是我们配的这个画的。所以请：
   a) 把这组工具的真实名字告诉我（完整名格式是 mcp__ + 服务名 seedream + 工具名，例如 mcp__seedream__text_to_image；以实际列表为准），我以后只按完整名字调用，不说「画图」这种含糊说法；
   b) 告诉我 WorkBuddy 设置里的自带生图 / 图片模型开关在哪、要不要关掉；
   c) 在结论里写清验收判据：seedream 出的图一定保存在
      图片目录/.seedream/images/<当天日期>/<工具名>/
      这个图片目录就是配置里的 SEEDREAM_DATA_ROOT（macOS 默认 ~/Pictures/Seedream，Windows 默认 C:\Users\<用户名>\Pictures\Seedream）。
      做法是：画之前先数一次这个目录里的文件数，画完再数一次，必须至少多出一个文件；对话里画了图但这里没有新增文件，就说明是内置模型画的，不算成功。
6. 失败就如实报告卡在哪一步、原始报错是什么，不要下「已配好」的结论。

网络或安装包失败时的备选方案（严格按顺序判断，不要一报错就跳到最后）：
a) 如果 uvx 从 GitHub 下载安装包卡住、超时或报错（公司网络打不开 GitHub）：
   - 告诉我需要哪个文件（seedream_image_mcp-4.2.0.post1-py3-none-any.whl），我从别处拷来放到指定目录；
   - 拿到本地文件后执行 uv tool install --from <本地文件路径> seedream-image-mcp；
   - 用 uv tool dir --bin 找到装好的可执行文件绝对路径，把 MCP 的启动命令改成它（参数留空，不再需要 --from）；
   - 其余配置和验证步骤不变。
   不要自己找镜像站下载，也不要改用 PyPI 上的 seedream-image-mcp==4.2.0（那个版本在这台网关会报 403）。
b) 只有 a) 也失败，并且你先说明原因、我明确回复「用兜底方案」之后，才执行单文件兜底：
   - 在本机建 ~/mcp/doubao-image/server.py，用 uv run --script 启动；
   - 只暴露一个 generate_image 工具，直接 POST https://ai.ctaigw.cn/v1/images/generations，参数：model=doubao-seedream-5.0-lite、response_format=b64_json、size 至少 1920x1920（总像素 ≥ 3686400，否则 400）；
   - 把结果保存为本地 jpeg 并返回绝对路径；配置写进 MCP 配置后同样要真实生成一张图验证；
   - 兜底版没有图生图、多图融合、组图、图片浏览能力，tools/list 只有 1 个工具，验收标准相应变成「generate_image 能真实出图」；必须在结论里写明这是兜底版，网络恢复后要换回正式版。
不要因为一次报错就默认用兜底版交差，也不要跳过 a) 直接写脚本。

这段提示词里没有需要我手动替换的内容，Token 也不用我填，你按第 2 步自己找就行。

最后必须按下面的格式给我结论，不要只回一句「已配好」：

【已完成】
- 装了哪个版本、改了哪个文件（写完整路径）、备份文件在哪

【验证结果】
- 握手拿到的工具个数；真实生成图片的完整路径和文件大小
- 任何一步没通过，写清卡在第几步、原始报错原文

【还需要你做的】（这些只有我能做，请按顺序一条一条列清楚，不要说「可选」）
1. 完全退出并重新打开 WorkBuddy（关闭进程，不是最小化窗口）
2. 打开 WorkBuddy → 左侧「连接器」→ 找到 seedream → 打开开关
   （只写配置不启用，对话里就看不到这个工具，这是最容易漏的一步）
3. 到 WorkBuddy 的设置里把自带的生图 / 图片模型关掉（位置按你查到的写清「在哪、点哪一项」；不关的话助手可能用自带的画，不走我们的 MCP）
4. 第一次画图如果弹出信任确认，点「允许」
5. 画图时用完整工具名，例如说「用 mcp__seedream__text_to_image 画一张图，尺寸 2K」（工具名以第 5 条给你的为准）
6. 画完确认：图片路径必须在 <图片目录>/.seedream/images/ 下面，或者该目录里多出了新文件；不在就说明是内置模型画的，重新用完整工具名再画一次

【做完之后你会看到】
- 「连接器」里的 seedream 是启用状态；工具列表里出现 6 个工具；画图返回的路径在 .seedream/images/ 下

【配置好后怎么问我】（必须列出，方便我直接复制；不要只教我说「画张图」，也不要说「用 seedream 画」这种模糊说法）
下面的指令每条都独立完整，可直接复制；不要用「同上」「同样先数后数」之类的指代。
1. 文生图：
   用 mcp__seedream__text_to_image 画一张图：一只橘猫在午后的窗台上晒太阳，写实摄影，柔和侧光，2K，不要文字和水印。画之前先数一次 .seedream/images/ 下的文件数（macOS：~/Pictures/Seedream/.seedream/images/；Windows：C:\Users\<用户名>\Pictures\Seedream\.seedream\images\），画完再数一次，告诉我多了几个文件，并把工具返回的本地绝对路径贴出来。
2. 图生图：
   先用 mcp__seedream__browse_images 找到我最近生成的那张图，再用 mcp__seedream__image_to_image 把光线改成黄昏逆光，主体和构图不变，2K。画之前先数一次 .seedream/images/ 下的文件数（macOS：~/Pictures/Seedream/.seedream/images/；Windows：C:\Users\<用户名>\Pictures\Seedream\.seedream\images\），画完再数一次，告诉我多了几个文件，并把工具返回的本地绝对路径贴出来。
3. 组图：
   用 mcp__seedream__sequential_generation 生成一组 4 张连贯画面：同一只橘猫从打哈欠到睡着，风格统一，2K。生成之前先数一次 .seedream/images/ 下的文件数（macOS：~/Pictures/Seedream/.seedream/images/；Windows：C:\Users\<用户名>\Pictures\Seedream\.seedream\images\），生成之后再数一次，告诉我新增了几个文件，并把工具返回的本地绝对路径贴出来。
4. 多图融合：
   用 mcp__seedream__multi_image_fusion 把我最近两张图（一张猫、一张窗台）合成一张，写实风格，2K。合成之前先数一次 .seedream/images/ 下的文件数（macOS：~/Pictures/Seedream/.seedream/images/；Windows：C:\Users\<用户名>\Pictures\Seedream\.seedream\images\），合成之后再数一次，告诉我新增了几个文件，并把工具返回的本地绝对路径贴出来。
5. 没走 seedream 时：
   刚才那次是 WorkBuddy 自带图片模型画的，.seedream/images/ 下没有新增文件。请改成调用 mcp__seedream__text_to_image 重画一次，不要用内置生图，并把新增文件数和本地图片路径贴给我。
6. 如果 WorkBuddy 的文生图指令仍被自带模型截胡，让我回到设置里关掉自带生图 / 图片模型再试。
每个示例都要带完整工具名，并以 .seedream/images/ 下是否新增文件作为是否走 MCP 的判据。
```

---

## 提示词 5：三端全配

```text
帮我把「AI 生图」工具一次配到 Claude Code、Codex、WorkBuddy 三个客户端，最后要求能真实生成一张图。

已经确认的事实（照抄，别改、别猜别的名字）：
- 网关：https://ai.ctaigw.cn/v1（必须带 /v1）
- 模型名：doubao-seedream-5.0-lite（点号、小写、结尾 lite）
- 安装包：
  https://github.com/wandouni/Seedream_MCP/releases/download/v4.2.0.post1/seedream_image_mcp-4.2.0.post1-py3-none-any.whl
- 版本应为 4.2.0.post1（显示 4.2.0 说明装错了）

统一的服务定义：
  名称：seedream
  命令：uvx 绝对路径（which uvx / where uvx）
  参数：["--from", "<安装包地址>", "seedream-image-mcp"]
  env：
    ARK_API_KEY=（Token 由你按第 2 步找到后原样填入，不要在这里保留占位符）
    ARK_BASE_URL=https://ai.ctaigw.cn/v1
    SEEDREAM_MODEL_ID=doubao-seedream-5.0-lite
    SEEDREAM_MODEL_PASSTHROUGH=true
    SEEDREAM_DEFAULT_SIZE=2K
    SEEDREAM_DEFAULT_WATERMARK=false
    SEEDREAM_DATA_ROOT=~/Pictures/Seedream

流程：

1. 环境：uvx --version；没装就装；然后
   uvx --from <安装包地址> seedream-image-mcp --version 预热，确认 4.2.0.post1。
2. Token：环境变量 ARK_API_KEY / SEEDREAM_API_KEY -> ~/.claude/settings.json 的 env.ANTHROPIC_AUTH_TOKEN -> 问我一次。找到后把真实值填进 ARK_API_KEY（填 Token 本身，不要填说明文字或占位符）。全程不打印 Token。
3. 写三处，每处先备份 .bak-<时间戳>：
   - ~/.claude.json -> mcpServers.seedream
   - ~/.codex/config.toml -> [mcp_servers.seedream] + .env 段（不能重复定义同一节）
   - ~/.workbuddy/mcp.json -> mcpServers.seedream（command 必须绝对路径；注意 WorkBuddy 写完配置还不会启用，必须由我在「连接器」页面打开；而且 WorkBuddy 自带图片模型，助手可能不用这个 MCP 而用自带的画，这两条都要列进最后的【还需要你做的】）
4. 验证（不能只检查文件）：stdio 启动服务 -> tools/list 应有 6 个工具且含 text_to_image -> 真实调用一次 text_to_image -> 确认图片文件存在、大小 > 0 -> 把路径给我。
5. 如果检测到我装了 cc-switch（存在 ~/.cc-switch/cc-switch.db），它后面会用自己数据库里的内容覆盖这两个文件，所以还要我点一次：打开 cc-switch -> 左侧 MCP -> 点「从应用导入」-> 确认框里勾选 seedream、Claude Code、Codex -> 确认。导入后再切 provider 也不会丢。若「从应用导入」里没有 seedream，再给我可粘贴的 JSON 让我手动补。
6. 失败就报告：哪一步、原始报错、你的判断，不要写「已完成」。

网络或安装包失败时的备选方案（严格按顺序判断，不要一报错就跳到最后）：
a) 如果 uvx 从 GitHub 下载安装包卡住、超时或报错（公司网络打不开 GitHub）：
   - 告诉我需要哪个文件（seedream_image_mcp-4.2.0.post1-py3-none-any.whl），我从别处拷来放到指定目录；
   - 拿到本地文件后执行 uv tool install --from <本地文件路径> seedream-image-mcp；
   - 用 uv tool dir --bin 找到装好的可执行文件绝对路径，把 MCP 的启动命令改成它（参数留空，不再需要 --from）；
   - 其余配置和验证步骤不变。
   不要自己找镜像站下载，也不要改用 PyPI 上的 seedream-image-mcp==4.2.0（那个版本在这台网关会报 403）。
b) 只有 a) 也失败，并且你先说明原因、我明确回复「用兜底方案」之后，才执行单文件兜底：
   - 在本机建 ~/mcp/doubao-image/server.py，用 uv run --script 启动；
   - 只暴露一个 generate_image 工具，直接 POST https://ai.ctaigw.cn/v1/images/generations，参数：model=doubao-seedream-5.0-lite、response_format=b64_json、size 至少 1920x1920（总像素 ≥ 3686400，否则 400）；
   - 把结果保存为本地 jpeg 并返回绝对路径；配置写进 MCP 配置后同样要真实生成一张图验证；
   - 兜底版没有图生图、多图融合、组图、图片浏览能力，tools/list 只有 1 个工具，验收标准相应变成「generate_image 能真实出图」；必须在结论里写明这是兜底版，网络恢复后要换回正式版。
不要因为一次报错就默认用兜底版交差，也不要跳过 a) 直接写脚本。

这段提示词里没有需要我手动替换的内容，Token 也不用我填，你按第 2 步自己找就行。

最后必须按下面的格式给我结论，不要只回一句「已配好」：

【已完成】
- 装了哪个版本；三端各自改了哪个文件（写完整路径）；备份文件在哪
- 三端状态：Claude Code / Codex / WorkBuddy 分别 已写入 / 无变化 / 失败

【验证结果】
- 握手拿到的工具个数；真实生成图片的完整路径和文件大小
- 任何一步没通过，写清卡在第几步、原始报错原文

【还需要你做的】（这些只有我能做，请按顺序一条一条列清楚，不要说「可选」）
1. 如果检测到 cc-switch：打开 cc-switch → 左侧 MCP → 点「从应用导入」→ 勾选 seedream、Claude Code、Codex → 确认
2. 完全退出并重新打开 Claude Code、Codex、WorkBuddy（关闭进程，不是最小化窗口）
3. 打开 WorkBuddy → 左侧「连接器」→ 找到 seedream → 打开开关（写进配置文件不等于启用，不开这里对话里看不到工具）
4. 到 WorkBuddy 设置里把自带的生图 / 图片模型关掉（按你查到的写清「在哪、点哪一项」；不关的话助手可能用自带的画）
5. 在三个客户端里各用带完整工具名的问法验证一次，例如「用 mcp__seedream__text_to_image 画一只橘猫，并把本地图片路径贴给我」，不要只说「画张图」；WorkBuddy 里再要求它报告 .seedream/images/ 下新增的文件数
6. 核对 WorkBuddy 画图的结果：图片必须在 <图片目录>/.seedream/images/ 下，或该目录新增了文件；不在就是内置模型画的，不算成功

【为什么要做第 1 步】
cc-switch 用自己数据库里的 MCP 列表覆盖 `~/.claude.json` 和 `~/.codex/config.toml`，不导入的话下次切 provider 就会丢。

【做完之后你会看到】
- 三端工具列表里出现 6 个工具；画图会返回本地图片路径；cc-switch 的 MCP 列表里有 seedream 且开关打开

【配置好后怎么问我】（必须按客户端分别列出，三端各一组；每条指令都要能直接复制，不要用「同上」「通用」之类的指代；不要只教我说「画张图」）
1. 在 Claude Code 里发（文生图，兼做验收）：
   用 mcp__seedream__text_to_image 画一张图，并把工具返回的本地图片绝对路径原样贴给我：一只橘猫在午后的窗台上晒太阳，写实摄影，柔和侧光，2K，不要文字和水印。
2. 在 Codex 里发（文生图，兼做验收）：
   用 mcp__seedream__text_to_image 画一张图，并把工具返回的本地图片绝对路径原样贴给我：一只橘猫在午后的窗台上晒太阳，写实摄影，柔和侧光，2K，不要文字和水印。
3. 在 WorkBuddy 里发（文生图，兼做验收）：
   用 mcp__seedream__text_to_image 画一张图：一只橘猫在午后的窗台上晒太阳，写实摄影，柔和侧光，2K，不要文字和水印。画之前先数一次 .seedream/images/ 下的文件数（macOS：~/Pictures/Seedream/.seedream/images/；Windows：C:\Users\<用户名>\Pictures\Seedream\.seedream\images\），画完再数一次，告诉我多了几个文件，并把工具返回的本地绝对路径贴出来。
4. 在 Claude Code 里发（图生图）：
   先用 mcp__seedream__browse_images 找到我最近生成的那张图，再用 mcp__seedream__image_to_image 把光线改成黄昏逆光，主体和构图不变，2K，并把工具返回的本地图片绝对路径贴给我。
5. 在 Codex 里发（图生图）：
   先用 mcp__seedream__browse_images 找到我最近生成的那张图，再用 mcp__seedream__image_to_image 把光线改成黄昏逆光，主体和构图不变，2K，并把工具返回的本地图片绝对路径贴给我。
6. 在 WorkBuddy 里发（图生图）：
   先用 mcp__seedream__browse_images 找到我最近生成的那张图，再用 mcp__seedream__image_to_image 把光线改成黄昏逆光，主体和构图不变，2K。画之前先数一次 .seedream/images/ 下的文件数（macOS：~/Pictures/Seedream/.seedream/images/；Windows：C:\Users\<用户名>\Pictures\Seedream\.seedream\images\），画完再数一次，告诉我多了几个文件，并把工具返回的本地绝对路径贴出来。
7. 在 Claude Code 里发（组图或多图融合）：
   用 mcp__seedream__sequential_generation 生成一组 4 张连贯画面：同一只橘猫从打哈欠到睡着，风格统一，2K；或者用 mcp__seedream__multi_image_fusion 把我最近两张图（一张猫、一张窗台）合成一张。两种任选一种，并把工具返回的本地图片绝对路径贴给我。
8. 在 Codex 里发（组图或多图融合）：
   用 mcp__seedream__sequential_generation 生成一组 4 张连贯画面：同一只橘猫从打哈欠到睡着，风格统一，2K；或者用 mcp__seedream__multi_image_fusion 把我最近两张图（一张猫、一张窗台）合成一张。两种任选一种，并把工具返回的本地图片绝对路径贴给我。
9. 在 WorkBuddy 里发（组图或多图融合）：
   用 mcp__seedream__sequential_generation 生成一组 4 张连贯画面：同一只橘猫从打哈欠到睡着，风格统一，2K；或者用 mcp__seedream__multi_image_fusion 把我最近两张图（一张猫、一张窗台）合成一张。生成或合成之前先数一次 .seedream/images/ 下的文件数（macOS：~/Pictures/Seedream/.seedream/images/；Windows：C:\Users\<用户名>\Pictures\Seedream\.seedream\images\），完成之后再数一次，告诉我新增了几个文件，并把工具返回的本地绝对路径贴出来。
10. 哪一端没走 seedream，就把这句发到那个客户端：
   刚才那次没有调用 seedream MCP，请直接调用 mcp__seedream__text_to_image 重画一次，不要用内置图片能力代替，并把工具的原始返回贴给我；如果是在 WorkBuddy 里，同时告诉我 .seedream/images/ 下新增了几个文件。
11. 把三端各自的实际工具完整名列给我（格式为 mcp__seedream__<工具名>，如 mcp__seedream__text_to_image），我按完整名字调用。
如果某端实际工具名与示例不同，按该端工具列表里的完整名替换后再发。
```
