# npx 安装助手

GitHub 仓库已于 2026-11-16 公开；首个 npm 发行版 [`dsh-trace-extension@0.2.19`](https://www.npmjs.com/package/dsh-trace-extension/v/0.2.19) 于 2026-11-17 发布。安装设计面向全新安装，不为此前的内部开发版补做迁移路径。

> 下文“后续候选的更新与恢复”描述本轮源代码，尚未发布为新 npm 版本。`0.2.19` 首发的安装生命周期证据可复用；新候选仍需用同一 tarball 完成真实 CLI、原生侧栏及重新登录验收，不能据此宣称新版已经交付。

## 用户入口

```sh
npx dsh-trace-extension setup
```

包内直接包含已构建插件、安装逻辑和许可证。默认安装不需要 GitHub 登录、私有仓库权限、源码克隆或前端构建。

当前要求：

- Node.js 20.19+ 和 npm/npx。
- Python 3.9+，供本地读取器运行。
- 支持本地插件、MCP Apps 和官方录制的 Codex 客户端。
- 首版面向 macOS / Codex；Antigravity 等尚未接入。

安装助手展示具体操作计划，确认后准备持久插件副本、登记本地来源、安装插件并配置录制。安装后手动完全退出并重新打开 Codex，再运行一个新任务并打开 **Codex Trace**。

## 检查与卸载

```sh
npx dsh-trace-extension setup --dry-run
npx dsh-trace-extension doctor
npx dsh-trace-extension uninstall
```

`--dry-run` 不创建持久配置或复制插件到用户目录。`doctor` 只读检查配置和文件，不把已安装或旧录制当作原生验收。`--yes` 可用于无交互终端，但不会绕过无关配置或文件修改冲突。`--json` 输出结构化结果。

`--codex-home`、`--trace-root` 可指定目录。默认创建供后续登录使用的录制 LaunchAgent；`--no-persist` 只配置当前登录会话。首次仍需重启 Codex，登录时与自动启动 Codex 的先后关系也需要实际验证。

## 后续候选的更新与恢复

新版发布后，安装、更新和可确认归属的修复使用同一入口：

```sh
npx dsh-trace-extension@latest setup --dry-run
npx dsh-trace-extension@latest setup
```

更新基线从正式 npm `0.2.19` 开始。首发 receipt 必须匹配已发布的 payload 身份；后续 receipt 保存原始 manifest 与配置模板以核验归属。历史开发来源、未知字段、内容修改、降级或同版本不同包内容会停止，不自动接管。

候选先准备新的持久 bundle，保留旧 bundle；同一候选重复安装复用现有内容。受管来源或 Codex 安装缓存中的已知缺失文件可以从相同包补齐。已有文件内容被修改时保留并停止，不能把用户编辑与文件损坏混为一谈。缓存中的额外文件不被修复操作删除；版本更新和卸载遇到未知额外内容会要求先复核。只有与当前 Python、已校验源码完全对应的生成 bytecode 才识别为运行缓存。

从公开 `0.2.19` 更新时，若旧稳定来源缺少插件文件，但首发身份、receipt、来源现存内容、安装归属与完整旧缓存均可独立核验，新助手会在同一计划和事务中从旧缓存补回确知的旧字节，再继续更新。它不使用新包内容冒充旧文件，也不会自动联网获取旧包。缓存不足或被修改时停止，要求从独立核验的原始归档或备份恢复明确缺失的路径后，再重试当前助手；公开 `0.2.19` 的原 setup 不具备这项修复能力，不能把重跑它当作恢复步骤。

安装在修改前记录私有 `operation.json`，使用同 profile 的操作锁防止并发修改。已知中断后的同版本重试会先展示恢复计划，按记录恢复仍匹配的写入，再继续安装；更新失败保留旧资源，或保留明确的恢复记录。doctor 会报告未完成操作及应重试的版本。恢复记录、配置或环境被外部修改时停止，保留文件供复核，不盲删状态文件。

Python 的绝对路径属于受管安装身份。旧解释器路径不可用时，可以在 PATH 中提供有效 Python 3.9+，或用 `DSH_TRACE_PYTHON=/absolute/path/to/python3` 选择解释器，再运行新助手的 setup。它会核对旧来源并重新固定受管副本与安装缓存中的启动路径，保留旧 bundle。无需手工改 receipt；未知或被编辑的来源仍要求先复核。

操作锁位于 `~/Library/Caches/dsh-trace-extension/`，按 CODEX_HOME 区分。恢复记录、备份和绝对路径属于本地私有资料，不应提交或上传。助手不为历史开发安装补做迁移。

## doctor 的检查范围

候选 doctor 分别报告配置、受管来源、Codex 安装缓存和后端探测，原生状态始终单独标为未验证。安装缓存检查会核对当前启用版本的实际文件，而不仅依赖 CLI 的 installed/enabled 元数据。npx 候选版本与已安装版本不同，本身不代表安装损坏。

仅在受管内容、安装缓存和解释器满足检查条件时，才将经过哈希复核的代码复制到私有临时目录，以空 HOME、空录制目录执行 MCP initialize/tools-list。准备文件有数量和 128 MiB 总量上限；后端子进程限制为 5 秒和合计 128 KiB 输出，超限会停止本探测创建的进程组。它不会执行被修改或来源不明的缓存文件，不读取真实聊天，也不把返回工具列表当作原生侧栏通过。无法安全确定时显示 unknown 或 not-run 及原因。

缺失文件可查看 setup 计划；被修改或未知的文件先保留并复核。不要为绕过保护直接删除录制、整个 CODEX_HOME 或恢复记录。未完成 setup 应先按 doctor 给出的原操作版本恢复，再卸载。

## 稳定的本地副本

Codex 登记的来源位于 `$CODEX_HOME/dsh-trace-extension/marketplace`，而不是 npx 缓存。清空 npm 缓存不会删除安装好的插件。受管副本使用已检测的 Python 绝对路径，减少 GUI PATH 差异。

重复安装校验自身文件后复用；同名陌生来源或被用户修改的受管内容会保留并报错。下一候选的已知发行版更新、修复与恢复规则见上文；公开前开发安装不构成迁移契约。

卸载保留录制和无关配置。仍被 Codex 来源登记引用的稳定副本保留，避免产生悬空路径。安装过程中如果已经尝试登记来源，后续失败也会保留可验证的副本并说明状态。

录制可能包含提示词、代码、工具输出和敏感值，分享前阅读[安全说明](../.github/SECURITY.md)。

## 维护者打包和验收

根开发包保持 `private: true`。独立 npm 发行包从显式白名单生成，只包含 CLI、安装与校验模块、bundle manifest、marketplace、已构建插件、图标和许可证。

```sh
npm ci
npm run build
npm run package:npm
npm run test:npm
```

候选目录为 `dist/npm/dsh-trace-extension`。`test:npm` 从真实 tarball 走 npm 本地安装路径；macOS 验收使用临时 HOME 与 fake Codex/launchctl，不触碰真实安装。它会删除临时 npx 缓存，再启动持久副本中的实际 Python 服务，并检查重复安装、doctor 和卸载。

```sh
npm pack ./dist/npm/dsh-trace-extension --ignore-scripts --pack-destination dist/npm --json
```

包无依赖、无 install/postinstall 脚本，不包含测试、用户配置、录制、日志或整个源仓库。安装仅在用户显式执行 `setup` 时进行。

## 发行记录与后续发布

`dsh-trace-extension@0.2.19` 是 2026-11-17 发布的首个 npm 版本，包含已构建前端、Python 读取器、安装器、图标及许可证。此前的开发版本不构成发行或迁移契约。后续兼容性评估从 `0.2.19` 开始；发布下一版本前需要明确并验证升级行为。

该版本已从公共 npm 仓库下载，在 macOS 的隔离 HOME / CODEX_HOME 中用真实 Codex CLI 验证全新安装、重复安装、doctor 和卸载。清空 npm 缓存后，已安装后端仍能提供工具和完整前端资源。测试后个人 Codex 配置与登录环境保持原状；重启 Codex 后的原生侧栏及再次登录时的启动顺序仍需验收。

维护者发布前检查真实 tarball 文件清单与完整性，完成安装验收并取得发布授权。直接发布已审阅的 `.tgz`，不要发布根开发包；发布账号须具备 npm 权限和有效认证。

## REA 参考

参考 [morluto/rea](https://github.com/morluto/rea) 的自包含 npm 分发，以及 setup/doctor/uninstall、计划确认、归属保护和文件完整性检查。研究基线为 [`552d1c7`](https://github.com/morluto/rea/tree/552d1c7108b99d1c9ec15d8b629ae07dc56d4714)，[MIT 许可](https://github.com/morluto/rea/blob/552d1c7108b99d1c9ec15d8b629ae07dc56d4714/LICENSE)。本项目为独立实现，没有复制 REA 代码。
