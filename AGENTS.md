# AGENTS.md

This file guides code agents working in the LangBot main repository. `CLAUDE.md` is a symlink to this file.

Read `ARCHITECTURE.md` before non-trivial backend, frontend, runtime, plugin, Box, MCP, persistence, or cross-repo SDK changes. This file is the working checklist; `ARCHITECTURE.md` is the system map.

## Quick Facts

- Python backend: `>=3.11,<4.0`, dependencies managed by `uv`.
- Frontend: `web/` is Vite + React Router 7 + shadcn/ui + Tailwind, managed by `pnpm`.
- Backend framework: Quart served by Hypercorn on `api.port`, default `5300`.
- Frontend dev server: `web/` on `3000`, with `VITE_API_BASE_URL` pointing at the backend.
- Plugin/Box/runtime contracts live in sibling repo `langbot-plugin-sdk`, pinned as `langbot-plugin` in `pyproject.toml`.

## Essential Commands

```bash
uv sync --dev
uv run main.py
uv run pre-commit install

cd web
pnpm install
pnpm dev
pnpm build
```

Useful focused tests:

```bash
uv run pytest tests/unit_tests -q
uv run pytest tests/integration -q
uv run pytest tests/integration/persistence -q
uv run pytest tests/manual/mcp_smoke.py

cd web
pnpm lint
pnpm test:e2e
```

Run the narrowest useful test first, then broader checks when confidence is needed.

## Where to Look

- Architecture map: `ARCHITECTURE.md`.
- Dev environment guide: https://langbot.app/docs/zh/develop/dev-config.
- Plugin runtime / CLI / SDK debugging: https://langbot.app/docs/zh/develop/plugin-runtime.
- API-key auth: `docs/API_KEY_AUTH.md`.
- Service API CLI: [`langbot-cli`](https://github.com/langbot-app/langbot-cli) (`lbctl`) manages running Workspaces; it is separate from the SDK's `lbp` CLI.
- Box deep-dive notes: `docs/review/box-architecture.md` and related files.
- In-repo skills: `skills/` is the single source of truth for LangBot agent skills.
- SDK repo: `../langbot-plugin-sdk/` when changing shared entities, plugin APIs, action protocol, `lbp rt`, or `lbp box`.

## Cross-Repo SDK Work

When changing SDK contracts used by LangBot:

```bash
# from langbot-plugin-sdk, with LangBot's .venv active
uv pip install .

# from LangBot, preserve the locally installed SDK
uv run --no-sync main.py
```

For standalone runtime debugging:

```bash
# in langbot-plugin-sdk
uv run --no-sync lbp rt
uv run --no-sync lbp box

# in LangBot
uv run --no-sync main.py --standalone-runtime
uv run --no-sync main.py --standalone-box
```

Config keys to verify in `data/config.yaml` / `src/langbot/templates/config.yaml`:

- Plugin runtime: `plugin.runtime_ws_url`, default Docker host `langbot_plugin_runtime:5400/control/ws`.
- Box runtime: `box.enabled`, `box.backend`, `box.runtime.endpoint`, Docker host `langbot_box:5410`.
- API/MCP auth: `api.global_api_key`.

## Change Rules

- HTTP API changes that should be agent-accessible must update the matching MCP tool in `src/langbot/pkg/api/mcp/server.py` and the relevant skill under `skills/` in the same pass.
- When changing Service API routes or capabilities used by `lbctl`, check compatibility with the separate `langbot-cli` repository.
- New schema changes use Alembic under `src/langbot/pkg/persistence/alembic/versions/`. LangBot 4.x does not support upgrading 3.x databases.
- New platform behavior belongs in platform adapters only for platform translation; pipeline/business logic belongs in `pkg/pipeline/` or services.
- User-facing strings must support i18n; follow the backend language rules below for server-generated content.
- Conversation payload columns, including new ones, must use `MediaReferenceText` and persist image references only. See the [media persistence contract](ARCHITECTURE.md#persistence-and-configuration).
- Interactive session lists use `SessionSummaryReader` to read only `monitoring_sessions`; `SessionSummaryWriter` maintains summaries in the source transaction. Historical initialization completes before writers start, never in requests or application background tasks. Follow the [conversation summary contract](ARCHITECTURE.md#conversation-summary-boundary) and keep `uv run pytest --required-suite session_summary` passing.
- Code comments and docstrings must be English.
- Keep compatibility and security in mind; LangBot is used in both self-hosted/community and toB deployments.
- Commit message format: `<type>(<scope>): <subject>`.

## Backend Message Language

- LangBot-owned business errors, runtime notices, and default messages sent to users must use the owning Workspace's message language. Keep this independent of each member's WebUI language; an unset Workspace language defaults to `en_US`.
- Reuse `src/langbot/pkg/i18n/` and the existing `message_language` entry in `WorkspaceMetadata`. Use `t()` with stable English templates and named parameters; add matching keys and placeholders to all eight catalogs: `en_US`, `zh_Hans`, `zh_Hant`, `ja_JP`, `es_ES`, `ru_RU`, `th_TH`, and `vi_VN`. Avoid new translation frameworks or duplicate language settings.
- Resolve language from a trusted Workspace or bot execution context, and isolate it across concurrent requests, tasks, and adapter callbacks. Browser language hints may supply account-only or unauthenticated response language, but must not override a resolved Workspace or authorize tenant selection. Reading/changing the setting requires `workspace.view` / `workspace.update`.
- Pipeline notices should be configurable in Pipeline output settings through `pipeline_notice()`. Blank overrides inherit the Workspace translation. Preserve user-authored text literally except for documented placeholders, and retain existing visibility switches. Do not rewrite historical messages or custom text when the language changes.
- China-only adapters and configuration/field validation diagnostics do not require localization. An adapter also serving international users is not exempt merely because it supports a Chinese platform.
- Preserve raw provider/plugin diagnostics, tracebacks, protocol values, and machine-readable error/status codes. Translate LangBot's own category or explanation around them; do not translate arbitrary errors with substring replacement. Plugin-authored messages remain the plugin's localization responsibility.
- Keep changes small and maintainable. Reuse existing persistence and response boundaries; delete obsolete fields only after verifying they have no remaining readers, including compatibility paths.
- When changing language behavior, verify catalog/placeholder parity, Workspace isolation and permissions, and Pipeline inheritance/custom overrides. Update affected configuration snapshots and API/MCP documentation. Implementation details and focused test locations: [Backend message language](docs/architecture/backend-i18n.md).

## Runtime Pitfalls

- Local stdio Plugin Runtime disconnects do not auto-reconnect; restart LangBot if that path breaks.
- Orphan runtime processes on `5400`/`5401` commonly break plugin debugging.
- Use `uv run --no-sync` after locally installing the SDK, or `uv` may restore the pinned package.
- A false Box “no backend” often means Docker is running but the current user lacks Docker socket permission.
- Do not confuse external MCP servers LangBot connects to (`pkg/provider/tools/loaders/mcp.py`) with LangBot's own `/mcp` server (`pkg/api/mcp/`).
- `CLAUDE.md` is a symlink to this file; edit `AGENTS.md`, not the symlink.

## Principles

- Keep it simple, stupid.
- Entities should not be multiplied unnecessarily.
- 八荣八耻

  以瞎猜接口为耻，以认真查询为荣。
  以模糊执行为耻，以寻求确认为荣。
  以臆想业务为耻，以人类确认为荣。
  以创造接口为耻，以复用现有为荣。
  以跳过验证为耻，以主动测试为荣。
  以破坏架构为耻，以遵循规范为荣。
  以假装理解为耻，以诚实无知为荣。
  以盲目修改为耻，以谨慎重构为荣。



## 文档记录约定（自动执行）

- **写法（硬性，先于格式）**：**业务语言打头，技术锚点紧随**——先说清「这是什么、谁受影响、用户/访客看到什么」，紧接着给出关键函数 / 字段名 / 配置项 / 代码位置，并**必须配一个真实例子或比方**。术语首次出现要解释一句；**关键字段与设计取舍不能因为"太技术"而删掉**。**判断标准（两条都要）：读完能说出「原来是这么回事」，且能照着找到对应代码/配置。** 只堆术语读者看不懂、或只剩大白话让人找不到地方，都等同于没写。
- **问题记录**：真实的故障/缺陷排查得出结论后（根因已定位或已修复），按 `docs/问题记录/问题记录方法.md` 的规范，把该问题追加到 `docs/问题记录/问题记录.md`（末尾有占位条目就替换，否则取最大编号 +1）。同一问题只记一次；后续进展回填原条目，不新建编号。写入后一句话告知：编号 + 标题 + 状态。
- **学习记录**：对话中出现需要解释的疑问（为什么 / 是什么原因 / 怎么理解 / 怎么排查）并已解释清楚时，按 `docs/学习记录/学习记录方法.md` 的规范，把该疑问与解答追加到 `docs/学习记录/学习记录.md`。一个疑问拆出多个知识点就分成多条（机制类 / 判别类 / 操作类）；同一主题只记一次，已有条目则补充而非新建。
- **分工**：具体事件（故障现象、排查过程、修复状态）走问题记录；从事件中提炼的可复用知识（机制、原理、判别方法）走学习记录；两者用相对链接互相引用，不整段复制。
- 两条记录都在结论稳定后整理，不打断正在进行的排查；用户明确说「不用记」时跳过。
