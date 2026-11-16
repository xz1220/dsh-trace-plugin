# Antigravity 插件适配

独立开发分支为 `codex/antigravity-plugin`，worktree 为
`~/.codex/worktrees/antigravity-plugin/codex-rollout-viewer`。主分支变更只单向
合入此分支，暂不合回 `main`，不创建合并 PR。不设置定时任务，由用户提醒同步或
发布新任务。

## 已完成的实现

`plugins/antigravity-dsh-trace/` 提供原生 Extensions → DSH Trace 面板。
Sidecar 使用 Antigravity 自带 SDK，外层页面托管共享 viewer，Python 子进程
提供独立的原生步骤读取接口。DSH 核心源码及 CSS 保持既有校验状态。

- 每个面板精确绑定自己的 Antigravity conversation ID；跨会话 thread/trace
  参数会被拒绝。
- 原生 reader 优先读取 `transcript_full.jsonl`；只有 compact transcript 时
  明确标记来源。没有记录时等待，记录出现后自动加载。
- 支持用户/助手消息、已记录的 thinking、工具参数与结果、错误和取消、搜索、
  历史分页、实时追加、延迟结果更新、Unicode 分块及重写后的重新同步。
- 界面区分原生步骤与模型原始请求。未记录的完整模型输入、工具声明、操作耗时
  及 TTFT 明确显示不可用，不从相邻步骤时间差推算。
- 主题桥接支持明确明暗提示及 CSS 颜色转换，覆盖 RGB、OKLCH/OKLAB、display-p3；
  语言使用可用的宿主通知，无通知时使用浏览器语言。
- 提供构建和可恢复安装/卸载脚本；旧安装移到独立备份目录，安装文件按 SHA-256
  核对。运行中的插件更新后需关闭再开启，不能把文件安装成功等同于原生已重载。

安装与开发命令见 [插件说明](../plugins/antigravity-dsh-trace/README.md)。

## 验收证据

2026-11-16 的自动检查：120 项 Python + 27 项 Node，共 **147 项通过**。
`npm run build:antigravity` 通过；DSH 99 个原样文件及 5 个既有适配校验一致。

受控浏览器检查使用完全合成的数据，实际点击验证了工具输入/结果、原生步骤
JSON、复制、搜索、折叠、未记录上下文说明；验证了实时追加保留选中详情、
两个面板隔离、空会话转为有记录，以及 302 条记录的早期历史加载。
1224/745/520/360px 下无页面横向溢出，工具栏从 y=0 开始，360px 详情抽屉可用。
明暗主题和中英文通知通过；OKLCH 浅色误判已修复并补了回归。

原生 Antigravity 2.32.1 已自动发现并启动插件；通过桌面 Extensions 菜单打开
面板，看到真实会话的用户输入与助手回复。用户也明确确认“已打开，能看到轨迹”。
真实日志只读检查通过，未把正文、token 或真实会话文件提交到 Git。

**最新版原生复验仍待继续。** 运行中的服务 cwd 指向更新前的备份目录，首次
原生观察也仍出现旧标签；安装文件的校验不能证明当前面板加载了最终代码。
用户正在使用 Antigravity，并明确表示“我稍后提醒你”。后续应等用户提醒，再
关闭/开启 DSH Trace 插件，验证最终版本及主题、详情和实时更新。不得自行重启
桌面或继续操作窗口。

受控浏览器空间 56 已 finish 一次、keep=[]；临时验证服务端口 49594 已停止。
不要再操作该空间，也不要停止 Antigravity 的原生服务。测试浏览器提示有更新，
本次沿用现有版本，未升级。

## 后续工作和同步规则

开始工作先检查分支、工作区修改和进行中的 Git 操作，再 fetch origin，比较
本地 main 与 origin/main 的新提交，仅正常合并到适配分支。保留已发布历史，
不覆盖用户工作，不强推，只推送 `origin/codex/antigravity-plugin`。

本轮开发期间主分支新增了 `8f0848e` 和 `d8f7c18`，涉及 Codex Trace 品牌及
0.2.19 版本；适配分支正在接入并验证这些变更。最终构建和原生复验状态应分别记录。
