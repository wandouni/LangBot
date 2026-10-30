# 豆包 Seedream 生图 MCP 接入指南（Claude Code / Codex / WorkBuddy）

面向使用 `https://ai.ctaigw.cn` 模型网关的同事，把豆包 Seedream 5.0 的生图能力作为 MCP 工具接入三个客户端。

> **原理一句话**：Claude Code、Codex 的主模型槽位只能放文本模型，图片模型放不进去，所以生图走 **MCP 工具**。三个客户端的配置内容相同，区别只在“配置写进哪个文件”。

| 客户端              | 配置方式                       | 配置文件                                                              |
| ------------------- | ------------------------------ | --------------------------------------------------------------------- |
| Claude Code + Codex | cc-switch 统一管理             | `~/.claude.json#mcpServers`、`~/.codex/config.toml#[mcp_servers]` |
| WorkBuddy           | 手动写文件（cc-switch 不支持） | `~/.workbuddy/mcp.json`                                             |

---

## 第 0 步：用直通版（无需加白）

网关 `https://ai.ctaigw.cn/v1` **只登记了别名** `doubao-seedream-5.0-lite`，既没有完整 Model ID `doubao-seedream-5-0-260128`，也不支持加白。而官方包 `seedream-image-mcp==4.2.0` 在启动时会把别名展开成完整 Model ID 再发请求，所以直连必然 `403 model_no_authorization`。

本指南因此使用**模型名直通版**，它和官方 4.2.0 只差一个开关：

| 项目     | 说明                                                                |
| -------- | ------------------------------------------------------------------- |
| 下载地址 | <https://github.com/wandouni/Seedream_MCP/releases/tag/v4.2.0.post1> |
| 改动     | 新增 `SEEDREAM_MODEL_PASSTHROUGH`，为 `true` 时配置里的模型名原样进请求体 |
| 许可证   | MIT，源码分支 `gateway-passthrough`，作者版权保留                   |
| 版本号   | `4.2.0.post1`，用于和官方 4.2.0 区分                               |

先确认网关认得这个别名（**不要把 token 明文写进脚本或配置里的注释**）：

```bash
curl -s -H "Authorization: Bearer $KEY" https://ai.ctaigw.cn/v1/models | grep -i seedream
```

看到 `doubao-seedream-5.0-lite` 即可继续；看不到说明 Key 或地址不对。

> 如果网关以后支持了完整 Model ID，把 `SEEDREAM_MODEL_ID` 改回 `doubao-seedream-5-0-260128`、`SEEDREAM_MODEL_PASSTHROUGH` 设为 `false` 即可，不用换包。

---

## 第 1 步：安装 uv（每台机器一次）

**macOS**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows（PowerShell）**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

安装后**先手动预热一次**，避免 MCP 首次启动时从 GitHub 下载安装包导致超时：

```bash
uvx --from https://github.com/wandouni/Seedream_MCP/releases/download/v4.2.0.post1/seedream_image_mcp-4.2.0.post1-py3-none-any.whl seedream-image-mcp --help
```

能看到 `seedream-image-mcp 4.2.0.post1` 的版本号，说明包已缓存到本机。

`uvx` 的默认位置：

| 系统    | 路径                                 |
| ------- | ------------------------------------ |
| macOS   | `~/.local/bin/uvx`                 |
| Windows | `%USERPROFILE%\.local\bin\uvx.exe` |

---

## 第 2 步：cc-switch 配置（macOS / Windows 通用）

两侧使用**同一份 JSON**，只有 `command` 一行不同。

操作路径：左侧栏 **MCP** → 页头 **添加 MCP** → 抽屉内「粘贴配置」贴入 JSON → 勾选「写入到」**Claude Code** 与 **Codex** → 添加 → 回到矩阵把对应开关打开。

**macOS**

```json
{
  "mcpServers": {
    "seedream": {
      "type": "stdio",
      "command": "uvx",
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
        "SEEDREAM_DATA_ROOT": "~/Pictures/Seedream"
      }
    }
  }
}
```

**Windows**：只改 `command` 与数据目录两处：

```json
      "command": "C:\\Users\\<用户名>\\.local\\bin\\uvx.exe",
```

```json
        "SEEDREAM_DATA_ROOT": "C:\\Users\\<用户名>\\Pictures\\Seedream"
```

要点：

- `SEEDREAM_MODEL_ID` 必须是网关登记过的别名 `doubao-seedream-5.0-lite`；写成完整 Model ID 会 `403`。
- `SEEDREAM_MODEL_PASSTHROUGH` 保持 `true`，它让上面这个别名原样发给网关。包默认就是 `true`，这里显式写出便于排查。
- `ARK_BASE_URL` **必须带 `/v1`**。客户端会拼成 `{base_url}/images/generations`，少了 `/v1` 返回 `401 api-key access forbit`。
- `SEEDREAM_DEFAULT_SIZE` 保持 `2K`。Seedream 要求至少 3,686,400 像素（≈1920×1920），小图直接 400。
- 保存后重启 Claude Code / Codex 才能加载新配置。
- cc-switch 数据库在 `~/.cc-switch/cc-switch.db`（Windows：`%USERPROFILE%\.cc-switch\cc-switch.db`），一般不需要手动改。

---

## 第 3 步：WorkBuddy 配置

cc-switch **不支持** WorkBuddy，需要手动编辑配置文件：

| 系统    | 文件                                  |
| ------- | ------------------------------------- |
| macOS   | `~/.workbuddy/mcp.json`             |
| Windows | `%USERPROFILE%\.workbuddy\mcp.json` |

把第 2 步的 `{"mcpServers": {...}}` 整体写入即可，但 **`command` 必须写绝对路径**——WorkBuddy 是 GUI 应用，读不到终端里的 PATH：

- macOS：`"command": "/Users/<用户名>/.local/bin/uvx"`
- Windows：`"command": "C:\\Users\\<用户名>\\.local\\bin\\uvx.exe"`

保存 → 重启 WorkBuddy → 首次调用弹信任确认，点允许（记录在 `~/.workbuddy/mcp-approvals.json`）。

也可以用 WorkBuddy 内置的 MCP 设置页添加，写入的是同一个文件，效果一致。

---

## 第 4 步：验证

对助手说：

> 用 seedream 生成一张「一只橘猫在窗台上晒太阳」的图

- 成功：返回本地文件绝对路径，图片落在 `<SEEDREAM_DATA_ROOT>/.seedream/images/<日期>/<工具名>/`
- 可用工具：`text_to_image`、`image_to_image`、`multi_image_fusion`、`sequential_generation`、`browse_images`、`get_model_info`

---

## 常见报错对照

| 现象                                        | 原因                                                          | 处理                                             |
| ------------------------------------------- | ------------------------------------------------------------- | ------------------------------------------------ |
| `403 model_no_authorization`               | 模型名不是网关登记的别名                                       | `SEEDREAM_MODEL_ID` 改为 `doubao-seedream-5.0-lite`，`SEEDREAM_MODEL_PASSTHROUGH=true` |
| `400 image size must be at least 3686400` | 尺寸太小                                                       | 用 `2K` 或 `2048x2048`                       |
| `401 api-key access forbit`                | `ARK_BASE_URL` 少了 `/v1`                                   | 改为 `https://ai.ctaigw.cn/v1`                 |
| 工具列表里没有 seedream                     | `uvx` 路径不对，Windows 用了裸 `uvx`                        | 写绝对路径，先手动预热一次                       |
| 首次调用长时间无响应后超时                  | 首次从 GitHub 下载安装包                                       | 先执行第 1 步的预热命令                          |
| 版本号显示 `4.2.0` 而不是 `4.2.0.post1`    | `args` 里还留着旧的 `seedream-image-mcp==4.2.0`               | 换成第 2 步的 `--from <wheel URL>` 写法          |
| 让主模型「切换成生图模型」                  | 主模型槽位不是文本模型                   | 主模型保持文本模型，生图只走 MCP                |

排查细节看 MCP 日志：`<SEEDREAM_DATA_ROOT>/.seedream/logs/seedream_mcp.log`（错误含完整堆栈，默认 5MB 轮转、保留 7 天）。

---

## 附录 A：单文件兜底方案（GitHub 不可达时）

主方案依赖 `uvx` 从 GitHub Release 下载。如果办公网连不上 GitHub，可改用下面这个单文件 MCP：它同样不翻译模型名，只有 `generate_image` 一个工具（没有图生图、组图、图片浏览）。把脚本保存为 `~/mcp/doubao-image/server.py`，源码见附录 B。

```json
{
  "mcpServers": {
    "doubao-image": {
      "type": "stdio",
      "command": "uv",
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

Windows 把 `command` 换成 `C:\\Users\\<用户名>\\.local\\bin\\uv.exe`，`args` 里的脚本路径换成 Windows 路径。
GitHub 恢复可访问后，删掉这条、换回第 2 步的配置即可。

---

## 附录 B：兜底脚本源码

单文件 MCP，依赖由 `uv run --script` 按文件头的 PEP 723 声明自动安装。

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
