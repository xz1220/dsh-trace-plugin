# 从这里继续：Codex Rollout Viewer

## 最新：0.2.11 修复冷开历史和实时跟随，已安装

用户最新明确报告两个 Bug：重启打开不显示历史，发消息后才出现；出现后初始只看到过去历史。当前源码与安装 **0.2.11**，分支 `codex/design-prototype`，无远端。本段 supersedes 下方版本状态。

- 原因：最新空录制遮住旧录制；桥接仅依赖宿主模型结果；实时只轮询一个 recording 且在 complete 后停止。
- 修复：无有效启动结果时主动调用原生入口；忽略无关结果，保护新启动选择；精确 root 选择最近有记录的录制，直到新录制有内容；实时在完成后继续通过 app-only `get_rollout_binding` 检查下一份录制；迟到完整快照重新读取；手动选旧录制保持固定，新增「返回当前聊天」。菜单底部显示界面版本 0.2.11。
- **48 Python + 15 Node = 63 项通过**；构建及 99 原样/5 原有适配校验通过。15 MCP 工具、app-only 权限、8 安装文件一致通过。真实归档完整上下文仍为 81,919 字符、原 SHA 不变。
- 协议页面实点通过：没有任何模型启动通知时直接读取历史；已完成录制发现新录制；新用户在回复前出现；当前回复和已开请求详情更新；下一份空录制不清空历史；手动固定、返回当前聊天、暂停/恢复和迟到快照刷新均通过。重开协议页直接读最新历史，360px 菜单无溢出。数据是隔离的受控官方格式录制，不能冒称原生通过。
- 报告 `reports/startup-live-0211-validation.json`；私有脚本/受控 bundle/详细记录在 `local-context/review/startup-live-0211/`。截图 `reports/screenshots/startup-live-0211-current.png`、`startup-live-0211-latest.png` 是协议页面。未新调模型。
- 安装根 `/Users/danielxing/.codex/plugins/cache/rollout-local/rollout-viewer/0.2.11`。运行中的原生 MCP cwd 仍是 **0.2.10**（进程21597/22494，可能后续变动），仅安装不代表已生效。已请求官方本地 `config/mcpServer/reload`，返回 `{}`，当前新版原生冷开验收未完成。
- 用户这次重启后的顶部确已是「轨迹 / ···」。CUA 还观察到本轮新用户/工具后来已出现，因此不应说原生永远不更新；修复覆盖冷开、空 bundle 和跨会话/已完成状态的缺口。更早官方录制保留菜单选择，没有实现全录制合并，也不使用普通 session 文件伪造完整请求。
- 后续在插件连接重载后重新打开 Viewer，核对菜单底部 **0.2.11**，先不发新消息验证历史；再验证新消息及当前执行自动出现。不能自动重启桌面/daemon，不能绕过 Codex 主窗口控制限制。整体目标不标 complete。
- CUA 本轮已选择 MCP Apps（browser id1），最新 handle `liveBugTab` 为 tab `1`。当前仅诊断读取，原生 0.2.11 的验收待继续。重开/压缩后先恢复文档、listTabs，再绑定新 tab；不要为恢复空列表重选 browser。真正观察到原生最终结果后，下一工具调用必须只含 CUA completion_summary，当前未冒称新版通过。
- Ego 空间 **30 已 finish 一次**、keep=[]，不能复用或再次 finish。预览 PTY **33768 已停止**，端口54604不再服务。旧空间21/22/23/26/29均已结束。测试配置为独立副本，不改用户录制目录配置。

---

## 0.2.10：顶部已收进「···」（历史状态）

用户最新要求：按 DSH 实机图把顶部也对齐，录制管理等辅助操作收进「···」，改完实际点击验证。随后问是否需要重启，并发来重新展开后仍是旧顶部的截图。本段为当前状态，下方旧版本说明仅供历史查阅。

### 已完成的改动与保存范围

- 源码及本机安装 **0.2.10**，安装根 `/Users/danielxing/.codex/plugins/cache/rollout-local/rollout-viewer/0.2.10`。仍在 `codex/design-prototype`，无远端。
- 删除 40px 的额外任务标题行。默认只有 36px「轨迹 / ···」导航；原版工具栏、时间线直接跟随。DSH 核心 CSS 未改；99 个上游文件原样、5 个原有适配。
- 录制选择、刷新、实时、主题、目录、语言、代理筛选和统计全部放进菜单。原任务标签及状态在菜单里。未添加不可用的「对话」标签。
- 菜单支持 Esc、外部点击、键盘移出、明确关闭及焦点恢复；短窗口滚动，目录错误在菜单里显示。菜单开关不改变列表选择和滚动位置。
- **46 Python + 10 Node = 56 项检查通过**；构建及 8 个关键安装文件一致检查通过。真实归档完整上下文仍为 81,919 字符、同一 SHA-256。
- Ego 实点覆盖菜单、目录成功/失败、刷新、语言、主题/实时、录制切换、代理筛选、冷开工具回助手、搜索、时长和轮次操作。1224/900/745/520/360px 无菜单溢出；360×260 短窗口可滚动。安装包预览另验证真实工具结果、来源链接、11 项完整上下文及原始请求/响应。

### 原生当前状态与用户下一步

用户重启已使 0.2.9 的新版解析器生效：live catalog 读到 70 份 schema 1/2 录制、0 份不可读。随后 CUA 已观察到当前 root `01a1d380-bb59-77b2-911c-57041de56dd3` 的真实长轨迹，包括本轮工具执行。这修正了下方「重启后尚未观察」的旧状态。

**但这次顶部更新尚未在原生生效。** 用户重新展开的 MCP App tab 为 `2`，标题仍是「任务 01a1d380」，常驻下拉/刷新/目录仍在；CUA 读到工具栏 top=76、没有「更多轨迹操作」按钮。两个 stdio MCP 进程 cwd 仍是 0.2.9 安装目录。0.2.10 安装/RPC 成功不能代表当前原生已经更新。

已通过官方本地 WebSocket 再次调用 `config/mcpServer/reload`，返回 `{}`，仅说明接收了配置重读。没有关闭桌面、停止 daemon 或杀掉用户插件进程；当前原生页面仍旧。请在本轮保存并结束后，用户完全退出并重开 Codex，再展开 Viewer；之后完成原生菜单、录制选择、搜索、详情联动的实际点击，才能记录新版原生通过。不要让用户重新配置录制路径，也不要把浏览器预览冒称原生截图。

CUA 仍沿用已选择的 MCP Apps 浏览器；最新 handle `topbarNativeTab` 对应 tab `2`，桌面重开后需先 listTabs，再绑定新 tab，不要重选浏览器来恢复空列表。压缩恢复先 `cua.rewriteDocumentation()`。真正重载并观察到 CUA 最终结果后，下一工具调用必须为只含 completion_summary 的 CUA 调用；当前新一轮仍在等待重载后的验收，未提前标成完成。禁止绕过直接控制 Codex 主窗口的既有限制。

### 证据与清理

- 当前报告 `reports/topbar-0210-validation.json`，说明 `docs/DSH_PARITY.md`。所有通过项区分本地/安装包/原生。
- 本地截图 `reports/screenshots/topbar-0210-reference.png`（安装包、受控数据）、`topbar-0210-menu-dark-360.png`。图片 Git 忽略，不能写成新版原生截图。
- 私有测试脚本、完整记录、官方重读脚本/结果、用户旧界面截图在 `local-context/review/topbar-0210/`。测试配置为独立副本，没有修改用户目录设置。
- Ego 空间 **29** 已成功 finish **一次**，keep=[]。不要复用，也不要再次 finish。此前的 21/22/23/26 也都已结束。
- 预览 PTY **27646/84124** 已 Ctrl-C 退出，端口 50789/53623 不再服务。初始化短用 session6332 也早已停止。
- 浏览器测试中两次脚本错误已修正：角色别名使用错误，以及折叠 JSON 的正文不可见不能用 innerText 判断。没有据此修改产品来迎合错误断言。修正后相关点击均通过，当前无观察到的界面运行错误。
- 整体目标不标 complete。上次 goal 为 blocked；新一轮有实质工作，不能沿用旧计数把本轮直接判为三轮受阻。

---

## 0.2.9：修复真实 schema 2 录制被忽略（历史状态）

用户最新问原生面板停在录制选择页是否符合预期。结论：不符合即开即看的最终目标。已查明并修复核心兼容性 Bug，而不是继续归因于没有开启录制。

- 磁盘已经存在 schema 2 的新录制，包括 `Respond to greeting`（thread `01a1d896-2de2-79c1-a75b-baded8aacc6d`，trace `031a1e3a-5456-4e23-86bc-b9c5c31ba97f`）及本聊天。旧 Catalog 只认 1，静默过滤了 2；前文“未找到录制”的索引结论需要据此勘误。
- GUI 环境及桌面程序/相关后台进程的 CODEX_ROLLOUT_TRACE_ROOT 都存在。不要因 sandbox 内 launchctl getenv 空输出就判断 GUI 没配置；已用 gui/uid 环境及目标进程单变量检查核实。
- 当前源码/安装 **0.2.9**，修复代码提交 `2994128`。支持 schema 1/2；事件版本必须匹配清单；未知格式显示原因和数量；空的已绑定聊天可通过刷新重新匹配；桌面引导和“录制中”状态已澄清。
- **46 Python + 10 Node = 56 项通过**。官方 0.169 reducer 接受真实问候录制；本机安装 RPC/文件一致通过，1 请求、0 工具、8 项输入（含工具声明）、138362 字符，3 块上下文。还抽查本聊天 schema2 三个请求，排除 additional_tools 后数量与官方一致。
- 本地安装版实际点击已显示真实 `hi` 和 `Hi! What would you like to work on?`；不支持格式提示及刷新精确重绑通过。截图 `reports/screenshots/schema2-029-greeting-preview.png` 是实际录制的本地预览，不能冒称新版原生截图。

**原生当前仍是旧连接，未完成新版最终验收。** 已在原生 DOM 确认挂载及目录读取（仍旧 1 条）。模型工具的 live catalog 也仍为旧解析器。已调用官方 `config/mcpServer/reload` 并收到 `{}`，当前打开面板仍未切到新后端；不要把 RPC 确认当作已刷新成功。没有停止或重启桌面/daemon。

CLI `app-server proxy` 是原始字节代理，控制 socket 上要用标准 HTTP Upgrade 的 WebSocket，不能直接发 JSONL；直接 JSONL 的两次超时已清理自己的代理进程。官方方法已用正确 WebSocket 调用成功。`mcpServerStatus/list` 对该问候 thread 返回 not found（未加载状态），不等于磁盘没有录制。

CUA 截图接口超时并 **kernel reset**，之前所有 JS handles 已失效。用户后续重载后，第一次 CUA 调用仅执行选择 MCP Apps 浏览器（例如 `let nativeBrowser = await cua.getBrowser({id:'mcpapps'})`），读完返回文档再 list/get 新 tab；不要用以前的 browser id 或 tab id。新一轮 CUA 原生验证在等待用户重载，尚未提交最终 completion_summary。早先“选择页已打开”的只读诊断部分已总结过，不等于新版验收。

本轮独立 Ego Space **26** 已 finish 一次，keep=[]；预览 PTY session18705 已 Ctrl-C 退出。勿再操作已结束空间。运行/点击记录与官方私有 reducer dump 在 `local-context/review/native-schema2/`（Git 忽略）。当前报告：`reports/native-schema2-validation.json`。

接下来需在用户方便时重载插件连接；最稳妥在本轮结束、其他任务空闲时重开桌面应用，再在测试聊天发一条消息并打开 Viewer。录制配置已经存在，原始录制也存在，不要让用户反复配置/重录来掩盖版本问题。不能自动关闭用户桌面或重启后台引擎。先验证自动匹配、请求/消息/上下文，再更新全项目 goal；不要提前 complete。

下方 0.2.8 为前一轮记录，当前状态以本段为准。

## 2026-11-14：实机图对齐修复及浏览器复验已完成

持续目标仍是完整 DSH 轨迹对齐和原生插件验收。用户最新要求：“按这张实机图继续对齐，把之前发现的交互问题都修复，再实际点击验证一遍。”本轮已完成已知问题修复和安装版 Web 实点；原生侧栏/新桌面录制仍待验收，不能把整体 goal 标 complete。goal 工具沿用此前 blocked 状态，本轮有实质进展，不新增阻塞计数。

### 当前代码与安装

- 源码及本机安装 **0.2.8**，代码提交 `08b349d`；分支 `codex/design-prototype`，没有远端。
- 安装根 `/Users/danielxing/.codex/plugins/cache/rollout-local/rollout-viewer/0.2.8`。
- DSH 固定提交 `e8f7b93a344964de3dca1ace9e72b6e4d6de87cb`。104 文件：99 原样、5 个有说明及哈希的适配；核心 CSS 未改。
- **43 Python + 10 Node = 53 项检查通过**。构建、8 个关键安装文件一致、14 工具及入口/RPC/调用定位/81,919 字符上下文检查通过。
- 新增后端运行文件 `server/trajectory-locales.json`，由构建时 `scripts/sync-trajectory-locales.mjs` 从同一前端词典生成，安装必须包含它。前端核心词典 8 语种，Codex 自定义面板为中文/英文回退。

### 已修复并实际点击

- D01：模式切换清除选区，双向及跨页面共享偏好更新均通过。
- D02：初始助手 metadata 保留空正文的 tool-call 引用；冷开工具即有“助手消息”链接，没先读助手正文。真实与受控录制均回跳成功。
- D03：默认等宽；时长及代码/JSON 展开换行偏好共享、持久化，跨录制/刷新/两页面同步通过。宿主不提供存储时为内存回退，不冒充可跨刷新保存。
- D04：宿主焦点 CSS 不再覆盖 DSH 搜索 input，内描边为 none。
- G01：`show_rollout_trace` 接受可选 callId；`get_rollout_record` 接受 rowId/callId 二选一。按调用定位会自动补历史并连接 inspectCallId；301 条历史中打开最早工具通过，DOM 37 行。公开入口仍只返回启动元数据。
- G02：8 语种宿主通知/回退、文档 lang、手动语言切换均通过。后端分组搜索使用同一词典，英文 Step、日文 ステップ 及切换时撤销旧匹配均通过。
- 宿主选择页会作废旧加载，350ms 迟到启动结果没有覆盖新空状态。
- 360px 目录入口竖排问题已修正；弹层、代理选择及深色抽屉通过。

顶部采用用户实机参照的标题/轨迹导航层级；当前 40px 标题 + 36px 导航。没有嵌套时仅显示时长/轮次/调用三项；有嵌套仍显示子调用。统计放目录菜单，搜索播报不增加布局行。保留本地录制功能和 Codex 三个附加请求标签，未知 TTFT 等数据不补造。

本轮还点击了真实归档三类折叠、完整上下文 11 项、受控完整/增量/角色过滤/目录、原样代码复制（真实剪贴板转发）、工具/代码/助手图片、灯箱/焦点、损坏重试、实际指针导出 114B SVG、键盘调宽、时间线点击定位及 1100/900/745/520/360px。无已观察到的运行时异常。详细范围见报告，不能扩大为所有状态组合都已验证。

### 证据与本机资料

- 当前验收：`docs/DSH_PARITY.md`、`reports/dsh-alignment-028.json`。
- 安装/RPC：`reports/dsh-installed-validation.json`；性能：`reports/dsh-performance.json`。
- 旧差异报告 `reports/dsh-difference-review.json` 已注明 0.2.8 解决结果，旧 0.2.7 复现记录保留。
- 用户真实参考图：`local-context/review/reference/dsh-user-web.png`（Git 忽略）。它是用户实际 DSH Web，不是先前组件驱动；其运行 commit 未核实。
- 当前展示图：`reports/screenshots/aligned-028-web-reference.png`、`aligned-028-dark-360.png`（受控数据，已人工查看；Git 忽略）。宽屏 1224×727 CSS px，详情手动调宽 508.5px；不能声称与参考图逐像素一致。
- UI 检查脚本/逐项记录及运行状态：`local-context/review/alignment-028/`。新增受控 bundle 为 review-comparison、review-focus、review-web-alignment，原数据都在本机。现有九场景生成器全量运行会重置实时场景，不要无故重建。
- 真实归档 trace `925371e4-ac04-4311-a063-62a563d04c5d`，root `01a1cfc4-5d25-7233-a749-66100b86a903`。完整上下文 SHA-256 `6f4c7f2bfb58f43a7e2f00f39acc2f6999b62f9d2980164ff3d2fc14154bd043`。

### 原生部分等用户方便时继续

用户对展开侧栏的异步问题明确回复 **“稍后打开”**，本轮没有重复询问。原生挂载和交互、重启后新桌面录制及当前聊天绑定仍待验收。2026-11-14 元数据检查仍未发现当前聊天 `01a1d380-bb59-77b2-911c-57041de56dd3` 的官方录制；没有重新运行模型实验来替代它。

CUA 先前明确禁止直接控制 Codex 主窗口，不能用系统脚本/CDP 绕过，不能自动退出 Codex。用户展开后复用 MCP Apps 绑定 `nativeBrowser`（id 2），先 tabs.list 再 tabs.get，不重选浏览器恢复空列表。压缩后继续 CUA 先 `cua.rewriteDocumentation()`；真正观察到 CUA 部分结果后，下一工具调用必须为只含 completion_summary 的 CUA 调用，恰好一次。当前 CUA 等待还未结束，不提前总结成完成。

安装不等于当前宿主进程已重载新资源；必要时让用户在方便时重新打开插件/聊天或重启，再验收。先前设置过桌面录制环境，届时复核继承情况。浏览器/harness 通过不能替代原生。

### 临时资源已清理

本轮 Ego Space **23**（DSH screenshot alignment QA）已成功 finish 一次，keep=[]；不要再次操作已结束空间。两个预览端口 62911/55768 均无监听。Space 21/22 也已在此前结束，不能复用。Ego 提示有更新，本轮未升级。

后续保护现有修改，只按明确文件名暂存；无远端不创建公开仓库。不要再做 mock，也不要把旧“仅保存”历史范围覆盖本段。若恢复后同一原生阻塞连续三个 goal turn 重现且无其他有意义工作，再遵守 blocked 规则；本轮修复不算无进展。

---

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
