# 从这里继续：Codex Rollout Viewer

保存日期：2026-11-12，Asia/Shanghai。用户要求先保存全部资料，后续再继续开发。

## 当前状态

- 项目目录：`/Users/danielxing/repos/codex-rollout-viewer`。最初聊天的工作目录是 `ai-research`，实际代码在本目录。
- 已实现并安装 **0.1.3**。插件 ID：`rollout-viewer@rollout-local`；显示名：**Rollout Viewer**。
- 实现分支：`codex/design-prototype`；最近功能提交：`54d544e`。没有配置 Git 远端，代码仅保存本机。
- 当前用户看到的是读取真实录制的本地浏览器预览。**原生 Codex 侧栏挂载尚未完成验收**，不能把预览或 MCP Apps 握手测试说成原生宿主已经通过。
- 已配置 macOS 当前登录会话的 `CODEX_ROLLOUT_TRACE_ROOT`，待 Codex 完全退出再打开后继承。尚未验证重启后的桌面端实际产出新录制。
- 本轮只整理交接资料，不继续增加功能，也不自动重启 Codex。

## 用户要做什么

参考 DeepSeek Harness（DSH）轨迹界面，为 Codex 做真正的侧栏插件。先跑通完整客户端提示词、工具调用和时间线，重点解决加载慢的问题，用真实任务验证后安装本机。

用户先要求源码和能力调研、真实请求录制实验，随后要求 DSH 设计系统拆解 HTML、可交互 mock，再批准实现插件。最近一次修改是修复基础对齐，已完成。

用户偏好：先阅读关键信息、做实际验证，再给结论；对外回复简短。不要反复请求已经授权的安装、修复或可逆操作。保留 DSH 的设计语言，继续迭代现有界面。

## 资料位置

| 资料 | 路径 |
|---|---|
| 插件源码、声明与可安装产物 | `plugins/rollout-viewer/`、`.agents/plugins/marketplace.json` |
| React 界面、宿主桥接、布局 | `src/viewer.jsx`、`src/host.js`、`src/ui.jsx`、`src/viewer.css` |
| 构建、录制、性能和安装验证脚本 | `scripts/` |
| 数据层测试 | `tests/test_store.py` |
| 产品与设计约定 | `PRODUCT.md`、`DESIGN.md` |
| 最终 DSH 交互 mock | `design/codex-trajectory-dsh.html` |
| DSH 设计系统拆解 | `design/dsh-design-system.html` |
| 最早的自定义设计稿 | `design/rollout-viewer.html` |
| DSH 源码缓存、固定版本与许可证 | `design/dsh-source/`、`design/dsh-sources.json`、`design/DSH-LICENSE.txt` |
| 实际验证及性能摘要 | `reports/` |
| 最新对齐效果 | `reports/screenshots/alignment-ledger.png`、`alignment-prompt.png`、`alignment-narrow.png` |
| 其他实际页面截图 | `reports/screenshots/installed-*.png` |
| 设计分析与 mock 截图 | `design/screenshots/` |
| 早期可行性实验、探针与官方协议 schema | `local-context/experiments/feasibility/` |
| 第一次真实请求录制实验 | `local-context/experiments/first-real-trace/` |
| 最新真实任务的指令、测试文件、输出与官方还原结果 | `local-context/validation/real-task/` |
| 最新完整 trace bundle | `local-context/recordings/trace-925371e4-ac04-4311-a063-62a563d04c5d-01a1cfc4-5d25-7233-a749-66100b86a903/` |
| 16 轮可见对话记录 | `local-context/conversation-visible.md`、`conversation-visible.json` |
| 本机环境、安装状态、归档来源 | `local-context/runtime-state.json` |
| 文件校验清单 | `local-context/manifest.json` |
| 固定版本与参考链接 | `handoff/SOURCES.md` |

`local-context/`、截图、DSH 源码缓存已经实际保存在本目录，但不加入 Git。源码、文档、脱敏报告和可安装 HTML 在 Git 中。要搬走全部资料，应复制整个目录，不能只依赖 `git clone`。无需复制 `node_modules`，可用 `npm ci` 重建。

## 已确认的能力与边界

1. 官方 Codex CLI **0.163.0** 包含可选的 `rollout-trace` 和 `codex debug trace-reduce`。
2. `CODEX_ROLLOUT_TRACE_ROOT` 在 Codex 进程启动前设置。输出 `manifest.json`、`trace.jsonl`、`payloads/*.json`。
3. 可以录制完整的**客户端实际请求**。基础指令在已验证请求中以 `developer` 输入项出现，界面保留原始角色，不强行改成 `system`。
4. WebSocket 后续请求可能只有增量。完整上下文按 `previous_response_id` 链，合并前序输入、前序响应 `output_items` 与本次 `input`；工具声明也保留。
5. 缺失前序请求时明确标为不完整，不冒充完整上下文。原始请求与还原后的上下文分别展示。
6. 工具参数、结果、代码单元、父子关联以及请求和工具的毫秒级起止事件可查看。
7. 不能从现有录制得到未返回的服务端内部信息、可读隐藏推理、逐 Token 流，或独立拆分排队、网络和纯生成耗时。
8. 旧执行事件不能事后补录；重启开启录制后产生的新执行可以再验证。普通 session 日志不是本插件当前数据源。

早期对话曾仅基于普通会话日志，低估了完整请求的可获得性；后来通过源码和真实实验修正。**以以上结果和真实 trace 验证为准**。`design/product-facts.md` 记录的是更早的 mock 阶段，不是最终实现状态。

## 实现结构

`plugins/rollout-viewer/server/store.py`：本地目录与标签、增量 JSONL 索引、请求链还原、工具关联、正文分块和缓存。只检索配置的 trace 根目录，不遍历普通 Codex 会话历史。

`plugins/rollout-viewer/server/main.py`：无第三方 Python 依赖的 stdio MCP 服务；还提供仅绑定 loopback、带临时访问 cookie 的预览服务。`/harness` 用于测试 MCP Apps postMessage 握手，不是真实 Codex 宿主。

`src/host.js`：MCP Apps 初始化与工具调用桥接；本地预览使用同一数据接口的 HTTP 适配。生产界面打包为单个 `assets/viewer.html`，运行时不需要 CDN。

公开工具：`list_rollout_traces`、`show_rollout_trace`。后者只返回启动元数据。

仅界面调用的工具：`open_rollout_viewer`、`get_rollout_overview`、`get_rollout_delta`、`get_rollout_detail`、`get_rollout_record`、`read_rollout_text`、`add_rollout_directory`。正文不经过公开模型工具返回。

原生入口由 `_meta["openai/ui"].entrypoints = [{"type":"thread"}]` 声明。按宿主传入的 `thread_id` / `threadId` 精确匹配；不匹配则让用户选择录制，绝不自动替换成“最新任务”。

## 性能做法与当前限制

- 首屏只读事件索引；选中记录才读 payload 正文。无变化轮询不再读取日志字节。
- 默认每页 200 条，单页最多 500 条；前端最多保留 1,000 条事件。时间线展示已加载记录，长历史需翻页。
- 正文每块 48,000 个 Unicode 字符，继续加载或“复制完整内容”会读取余下分块。
- 实时增量轮询间隔 1.5 秒，页面隐藏时跳过；录制结束后停止。
- 单日志上限 256 MiB，单 payload 上限 64 MiB；超限报错，不静默截断。
- payload 与文本缓存各有容量边界，最多保留 4 个 trace 索引、16 个上下文还原结果。
- 工具到后续请求的关联查找以结构化 `call_id` 为依据，最多检查 128 个后续候选请求。
- 目前支持 schema 1。多 Agent、压缩等分支尚未用新的真实复杂任务做端到端覆盖。

本机后端实测（Python 3.9.6 / arm64）：真实 7 条事件首索引 0.336 ms；合成 10,000 条事件首索引 **93.528 ms**、重复分页读取中位 **0.652 ms**。首屏 payload 读取数为 0，无变化轮询额外日志读取为 0。见 `reports/performance.json`。这些不是原生 Codex 面板整体加载耗时，文件系统缓存也可能已热。

## 验证结果

第一次真实录制：2 次模型请求、1 次工具调用。请求耗时 3593 / 1988 ms，工具 77 ms。原始数据和校验脚本已从 `/tmp` 复制进 `local-context/experiments/first-real-trace/`。

最新真实录制：3 次模型请求、2 次终端工具、2 个代码单元，共 7 条标准化记录。先执行 `/bin/cat fixture.txt`，再单独执行 `/usr/bin/wc -l fixture.txt`。返回值包含中文和行数。

- trace ID：`925371e4-ac04-4311-a063-62a563d04c5d`
- root thread ID：`01a1cfc4-5d25-7233-a749-66100b86a903`
- 最后请求还原 11 条上下文项，81,919 字符、2 块正文；基础、developer、workspace、用户指令和工具输出的受控标记均存在。
- 三个请求的上下文项数（排除额外工具声明项）与官方 `trace-reduce` 结果一致。
- 测试任务退出码 0。工具返回与测试文件吻合，两个工具均可关联到后续模型请求。
- 11 项数据层测试通过，覆盖缺失前序、Unicode 分块、部分写入、增量结束、历史分页、路径约束等。
- v0.1.2 完成真实数据界面交互、增量刷新和 MCP Apps 握手测试，详见 `reports/browser-validation.json`，该报告版本号有意保留。
- v0.1.3 完成对齐修改，验证了 1100 / 900 / 745 / 520 / 360 px 布局；安装包与源码校验一致，安装包 RPC 验证通过。见 `reports/installed-validation.json`。

原始研究聊天 ID：`01a1ceb8-fa92-7710-b52e-f2559b3f45f8`。它此前没有开启完整 trace，不能把上述验证任务说成该聊天的完整轨迹。

## 最近修复与设计约定

- 工具跳到模型请求时，旧详情状态曾导致空白；Inspector 以 trace / row ID 为 key 隔离。
- 增量更新补齐请求/工具计数；用行版本使已打开的结果在完成后刷新，避免读到旧缓存。
- 使用 DSH 原始主题和组件 CSS，MIT 许可证与署名已保留。没有重新设计一套配色。
- v0.1.3 使用 12 px 外侧边距、72 px 事件列、44 px 事件标签。表头、正文与时间线起点均为 80 px。
- 表格和详情标题栏均为 30 px。工具栏图标改用统一尺寸 SVG；提示词的角色、标题、继承标记与字数使用固定列。
- 小于 760 px 时详情为抽屉，仍可关闭；保留深浅色、搜索、子调用折叠、时间线缩放和拖选。

## 下次优先做什么

1. 先读取本文件、`README.md` 和 `git status`，继续现有代码，不要重新做 mock。
2. 验收真实 Codex 侧栏：让桌面端重新加载新插件后，从当前聊天右侧工具菜单打开 **Rollout Viewer**。本次 Computer Use 曾无法操作 Codex 原生主界面；不要绕过这一限制，也不要用浏览器 harness 冒充宿主验证。必要时请用户打开入口，再检查可用的 MCP App 表面。
3. 验证桌面端新任务是否实际产出官方 trace、入口是否绑定对应 root thread，以及原生宿主内的加载和交互。
4. 在此基础上再决定后续范围：大量事件的前端交互测量、复杂工具错误、多 Agent、压缩和取消等真实任务覆盖。它们是待做项，不是已完成结果。

无需重跑模型实验来重新证明已有三个请求的结果；归档 bundle 和受控测试材料都在本目录。未经新的任务要求，不继续扩展功能。

## 常用命令

在项目根目录执行：

```sh
npm ci
npm run build
npm test

codex plugin marketplace add /Users/danielxing/repos/codex-rollout-viewer
codex plugin add rollout-viewer@rollout-local
```

重新打开归档真实数据预览（终端会打印新的 `/open/...` 访问地址）：

```sh
python3 plugins/rollout-viewer/server/main.py --preview \
  --config-file local-context/viewer-config.json \
  --trace-id 925371e4-ac04-4311-a063-62a563d04c5d
```

录制新的 CLI 任务：

```sh
python3 scripts/record.py -- exec --ephemeral "你的任务"
```

配置 macOS 后续启动的桌面进程录制（当前登录会话有效，之后手动完全退出并重开 Codex）：

```sh
python3 scripts/record.py --desktop-env
```

关闭该环境设置：`launchctl unsetenv CODEX_ROLLOUT_TRACE_ROOT`，之后重启 Codex。不要为了续接而自动关闭用户正在工作的应用。

本机安装目录：`/Users/danielxing/.codex/plugins/cache/rollout-local/rollout-viewer/0.1.3`。修改后应重建并更新安装版本，避免混用旧安装包。

保存时的可见预览地址为 `http://127.0.0.1:58668/`，只是临时进程，不能当永久入口。新的浏览器需要使用服务打印的 `/open/...` 地址获得 cookie。原始录制目录为 `~/.codex/rollout-traces`，完整副本已放入本项目。

早先安装的第三方 `codex-trajectory@icesixgod` 1.1.0 仍是另一个插件；不要误操作它，也不要把它的工具 namespace 当成 Rollout Viewer。
