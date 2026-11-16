# Antigravity DSH Trace

在 Antigravity 的右侧 **Extensions → DSH Trace** 中查看当前会话的原生步骤。
面板自动绑定当前 conversation ID，复用项目现有 DSH 工具栏、时间线、账本和详情。

## 安装与更新

在本分支的项目根目录执行：

```sh
npm ci
npm run build:antigravity
python3 scripts/install-antigravity.py
```

安装到 `~/.gemini/config/plugins/antigravity-dsh-trace/`。新插件由 Antigravity
自动发现，从一个已有聊天的 Extensions 菜单打开即可。运行需要 Python 3.9+
及 Antigravity 自带的 Sidecar SDK；前端已经打包，不需要在安装目录运行 npm。

更新已运行的插件后，在 **Customizations → DSH Trace** 中关闭再开启插件，
然后重新打开面板。运行中的 Sidecar 可能仍使用旧安装目录，安装文件更新不能
单独证明面板已经加载了新代码。

安装器按 SHA-256 验证文件，将旧安装保存在
`~/.gemini/config/plugin-backups/antigravity-dsh-trace/`。已有的非本安装器管理
的同名目录会被保留并提示错误；安装器不改写全局 `config.json`。

预览操作与可恢复卸载：

```sh
python3 scripts/install-antigravity.py --dry-run
python3 scripts/install-antigravity.py --uninstall
```

卸载会把本安装器管理的插件移入备份目录。也可以通过 Customizations 管理插件。

## 数据与可用能力

仅读取当前会话的
`~/.gemini/antigravity/brain/<conversation>/.system_generated/logs/`。
优先读取 `transcript_full.jsonl`；只有 compact transcript 时会在来源元数据中
明确标记。没有日志时等待，日志出现后自动显示，不选择其他会话的记录。

| 内容 | 展示方式 |
| --- | --- |
| 用户、助手及已记录的 thinking | 账本、消息详情、搜索 |
| 工具名称、参数、结果、错误及取消状态 | 关联原生调用，详情保留原始步骤与结果 |
| 原生步骤 JSON | 可查看、分块读取及复制 |
| 步骤时间戳 | 保留日志中记录的时间，标为“步骤时间戳” |
| 输出 token | 只展示日志中明确给出的数值 |
| 输入及缓存 token 原始计数 | 保留在原生步骤 JSON；不推断其是否为互斥计数 |
| 原始模型请求、完整模型输入、工具声明 | 明确显示未记录 |
| 操作耗时、TTFT、生成速度 | 没有来源数据时显示未记录或不可用 |

`GENERIC` 工具结果按 Antigravity 内置 Swarm 所用的原生调用顺序规则关联。
未知步骤和无法唯一关联的结果保留为独立记录。不会从相邻步骤的时间差推算耗时。

支持历史分页、增量追加、运行中结果更新、部分尾行、源文件重写后的重新同步、
搜索、折叠和详情分块。单个日志上限 64 MiB，超限会显示错误。

## 宿主与开发

`sidecars/trace-viewer/` 使用 `sidecar_sdk` 托管页面。外层面板将当前会话 ID、
主题和可用的语言通知传给共享 MCP Apps viewer；无语言通知时使用浏览器语言。
Python 子进程通过 stdio 提供只读数据接口；进程异常后下一次调用可重新启动。
不启动 Agent 任务、不向其他聊天发送消息，不执行轨迹中的命令或链接。

包装页只接受自身同源 viewer 的 JSON-RPC 消息。数据接口使用 SDK 认证的 POST，
并拒绝与当前面板不匹配的 conversation/thread/trace 参数。

显式开发配置：`ANTIGRAVITY_DSH_PYTHON` 指定 Python 可执行文件；
`ANTIGRAVITY_NATIVE_DATA_ROOT` 指定测试或其他本地 Antigravity 数据根目录。
测试目录需要包含 `brain/<conversation>/.system_generated/logs/`。

```sh
npm test
npm run build:antigravity
```

`tests/fixtures/antigravity.jsonl` 完全由合成数据组成。原生窗口验收、受控浏览器
验证和真实会话只读检查分别记录在 `reports/antigravity-validation.json`。
