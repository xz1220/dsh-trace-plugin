# Antigravity 插件适配

本分支负责把现有 Trace Viewer 接入 Antigravity 的右侧 Extensions 面板。
开发分支为 `codex/antigravity-plugin`；持续接收 `main` 的变更，暂不合回主分支。

## 主分支同步

主仓库与适配 worktree 各自保留工作目录。开始工作前先检查当前分支、未提交
修改和进行中的 Git 操作，再 fetch `origin`。同时比较本地 `main` 和
`origin/main`，只把尚未包含的提交合入适配分支。

有未提交工作或其他任务正在修改此 worktree 时，不覆盖、不自动暂存他人的
修改。同步后的验证按变更范围执行；出现需要取舍的冲突时保留两边成果并记录
问题。所有推送明确指定 `codex/antigravity-plugin`，不推送 `main`，不强推。

Codex 当前聊天已启用「跟进 Antigravity 适配分支」，每 4 小时检查主分支更新、
同步适配分支及验证兼容性。没有新的主分支提交时不产生空提交；适配进度与
验收结果在本文中继续记录。

## 本机已确认的接入机制

检查对象：Antigravity 2.32.1；Antigravity IDE 的 VS Code 扩展是独立机制。

- 自定义 UI sidecar 可放在 `~/.gemini/config/sidecars/<id>/`，也可随插件放在
  `~/.gemini/config/plugins/<plugin>/sidecars/<id>/`。
- `sidecar.json` 声明启动命令、`has_web_ui: true` 以及
  `ui_config.views[].entrypoint: SIDECAR_UI_ENTRYPOINT_AUX_PANE`。
- 内置 Swarm 用 `SidecarApp` 注册 HTML、JS、CSS 和数据 API，由 `app.run()`
  启动；界面通过宿主注入的 `window.sidecar` 访问接口和宿主操作。
- 另有 MCP Apps 接入方式：在工具 `_meta` 中声明 `ui.resourceUri` 和
  `com.google.antigravity/ui.entrypoints`，其中 `aux_pane` 对应右侧面板。

证据来自本机 `~/.gemini/antigravity/builtin/` 中的
`skills/ui-plugin-navigation/SKILL.md`、`skills/mcp-app-development/SKILL.md`
以及 `plugins/swarm/sidecars/swarm_board/`。以上确认了文档和内置示例的接入
机制，尚未注册本项目的自定义面板，也未完成原生验收。

## 第一阶段：面板接入

优先在独立目录编写 Antigravity 适配器，复用
`plugins/codex-dsh-trace/assets/viewer.html` 和现有 Python MCP 后端，避免复制
DSH 源码或改变 Codex 插件的默认运行行为。

先验证 Sidecar SDK 的可用入口、启动约定和主题/语言桥接，再完成插件 manifest、
服务入口及安装/卸载说明。若用 wrapper iframe 托管原 viewer，需验证来源窗口、
JSON-RPC 请求/响应、错误和关闭生命周期；MCP 后端只经显式绑定读取数据。

现有 viewer 的 `open_rollout_viewer` 依赖 Codex 的 `thread_id` / `threadId`。
Antigravity 的 conversation ID 不能用于这一匹配。第一阶段若展示既有 Codex
官方录制，必须显式选择或配置对应 trace/thread，不自动打开“最新录制”。

## 第二阶段：Antigravity 原生数据

单独调查 Antigravity 可用的轨迹数据与读取接口，确认请求上下文、消息、工具
调用及耗时的来源和完整性，再设计数据适配层。现有 Codex 官方 rollout-trace
解析器不构成对 Antigravity 原生轨迹格式的支持。

## 验证与进度

- 2026-11-16：从 `origin/main` 的 `9d9d892` 创建独立 worktree 和分支，完成
  接入机制调查及开发约束。实现与原生验收待继续。
- 基线验证通过：依赖已用 `npm ci` 初始化；`npm test` 的 104 项 Python 与
  18 项 Node 检查全部通过；`npm run build` 通过，DSH 99 个原样文件与 5 个
  既有适配校验一致。npm 默认缓存存在权限问题，本次使用独立临时缓存，未更改
  系统缓存所有权。后续按实际适配增加协议和绑定验证，原生面板验收另行记录。
