# 个人 Workspace：每个账号一个独立空间

## 这是什么

在 OSS 版 LangBot 里，同一个实例下的每个 Web 账号现在拥有**自己的 Workspace**：各自创建的机器人（pipeline）、知识库、模型供应商、监控会话、插件和配置互相不可见。管理员也不再拥有跨工作区视角——`admin@vocational.local` 只看到自己的 Default Workspace。

一个真实例子：升级前，`admin@vocational.local` 和 CAS 账号 `204618` 都能在机器人列表里看到同一个企微机器人；升级后，`204618` 首次 SSO 登录会进入一个空的个人 Workspace，只能看到自己创建的机器人，管理员的历史机器人和知识库仍留在 Default Workspace。

实现不新增业务列，也不改 16 张资源表：可见性边界仍是既有的 `workspace_uuid`。新增的是「谁来拥有哪个 Workspace、无选择器时解析哪一个」这一层。

## 关键代码与配置

- 策略：`src/langbot/pkg/workspace/policy.py::PersonalWorkspacePolicy`
  - `workspace_limit=None`（不限数量）、`members_enabled=False`、`invitations_enabled=False`、`multi_workspace_enabled=False`、`personal_workspace_enabled=True`。
  - `multi_workspace_enabled=False` 很关键：它让 OSS 继续走本地目录、无 Cloud directory projection 的既有持久化路径，只是放开「多个 local Workspace」。
- 账号解析：`src/langbot/pkg/workspace/collaboration.py::resolve_account_workspace`
  - 请求没有 `X-Workspace-Id` 时，个人策略下查询该账号在本实例的 active membership，必须**恰好 1 个**；否则 `WorkspaceNotFoundError`，不会猜。
- 个人 Workspace 供给：`src/langbot/pkg/workspace/service.py::ensure_personal_workspace`
  - slug 为 `personal-{account_uuid}`，UUID 由 `personal_workspace_uuid(instance_uuid, account_uuid)` 确定性生成。
  - 幂等：已有 active membership 直接返回；重复 SSO 登录不会建第二个空间。
- Default Workspace：slug=`default`，承载实例级资源和管理员历史数据。
  - `get_default_workspace()`、`get_default_execution_binding()` 是所有「无租户参数」调用点的唯一解析目标。
  - 全局 API Key、`lbctl`、公开插件资产、进程日志、存储分析都固定作用于 Default。
- SSO 建号：`src/langbot/pkg/api/http/service/user.py::_ensure_sso_workspace`
  - 已有 active membership → 返回它（管理员留在 Default）。
  - 没有 membership → 在当前事务内创建个人 Workspace，角色 owner。
  - 已被禁用/移除的 membership 不会被激活，管理员移除优先于身份提供商。
- 迁移：`src/langbot/pkg/persistence/alembic/versions/0043_personal_workspaces.py`
  - 升级时把非 Default owner 的 active membership 置为 `removed`，为这些账号创建个人 Workspace、执行状态和 owner membership，复制 Default 的 `message_language`，并吊销所有 pending 邀请。
  - 可重复执行：已存在的 slug/membership 会复用。
- 插件：`src/langbot/pkg/plugin/connector.py::_resolve_runtime_profile`
  - 个人空间要能装插件，必须使用 SDK 的 `shared` 运行时 profile。
  - `plugin.runtime_profile: auto` 在「个人策略 + 外部 WebSocket Runtime（Docker）+ `LANGBOT_PLUGIN_RUNTIME_CONTROL_TOKEN` 已配置」时解析为 `shared`；缺 token 时回退 `oss_dev` 并告警（插件只在 Default 可用），显式 `shared` 缺 token 则启动失败。
- 权限：`src/langbot/pkg/api/http/authz.py::permissions_for_role(members_enabled=False)`
  - 剔除 `member.*`、`workspace.delete`、`billing_link.manage`，保留 `resource.manage`、`audit.view` 等；前端成员/邀请面板因没有权限自动消失。

## 边界与限制

- **PostgreSQL OSS 不支持个人 Workspace**：`pkg/persistence/mgr.py` 会把每个事务的 `langbot.workspace_uuid` 钉死为单个 local Workspace，多 Workspace 会串号。迁移 `0043` 在 PostgreSQL 上需要创建个人空间时直接失败；`ensure_personal_workspace()` 与启动时 `validate_workspace_layout()` 也会拒绝。生产使用 SQLite，不受影响；PG 单账号新装仍可工作。
- **迁移不可逆**：`0043.downgrade()` 只在实例恰好有一个 local Workspace 时重建旧索引，否则拒绝执行。回滚旧镜像必须恢复升级前的数据库备份，不能只切镜像。
- **进程日志与实例级存储分析只属于 Default**：个人 Workspace 即使有 `audit.view`，访问 `/api/v1/logs` 也会得到 404；`/storage-analysis` 只返回该 Workspace 的 scoped storage/skills，不暴露 database/logs/vector/temp/tasks。
- **历史会话留在 Default**：历史 `monitoring_sessions` 没有可靠的账号归属，无法按 Web 账号拆分。
- **个人空间初始为空**：没有模型供应商、知识库和机器人，用户需自行配置；首次登录会看到初始化向导（`wizard_status=none`）。
- **共享永久关闭**：邀请创建/成员管理在策略层被禁用，邀请接受/检查返回 403 `sharing_disabled`。

## 部署与验证

部署顺序（生产）：

1. 完整备份数据库与数据目录。
2. 在**备份副本**上预检：`select count(*) from workspaces where source='local';` 应为 1；每条 `plugin_settings` 有 `artifact_digest`，且 `binary_storages` 有对应 `plugin_artifact/package.lbpkg`。
3. 本机构建并推送镜像，`docker compose up -d`；`0043` 随启动执行。
4. 验证：
   - admin 仍能看到历史机器人、知识库、企微机器人和监控会话。
   - 普通账号首次 SSO 登录进入空的个人 Workspace，看不到 admin 资源，可自行配置 provider 并安装插件。
   - `select count(*) from workspaces where source='local' and type='personal';` 等于非 Default owner 的账号数。
   - Default 只剩 admin 一个 active owner。
   - 插件运行时日志无 `artifact_missing` / `requires nsjail`。

回滚：恢复升级前数据库备份，再切回旧镜像。旧镜像的 `ensure_singleton_workspace` 遇到多个 local Workspace 会启动失败。

## 相关记录

- 迁移实现：`0043_personal_workspaces.py`
- 租户机制背景：`docs/multi-tenant/workspace-multi-user-architecture.md`
- 鉴权上下文：`src/langbot/pkg/api/http/controller/group.py::_resolve_account_context`
