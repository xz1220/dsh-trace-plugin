# npx 安装助手

GitHub 仓库已于 2026-11-16 公开；首个 npm 发行版 [`dsh-trace-extension@0.2.19`](https://www.npmjs.com/package/dsh-trace-extension/v/0.2.19) 于 2026-11-17 发布。安装设计面向全新安装，不为此前的内部开发版补做迁移路径。

> `0.2.20` 已发布并设为 npm 默认版本，实际下载包已完成哈希核验，用户已确认可以打开侧栏。`0.2.21` 正在准备发布，将交付下文的紧凑机器人终端交互。侧栏打开不单独证明新录制生成、实时事件更新或重新登录后的启动顺序；各项验证仍按对应版本和证据判断。

## 用户入口

在自己信任的仓库外目录运行：

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

## rollout-local 来源冲突

`Marketplace 'rollout-local' uses a different or unknown source` 表示所选 Codex 配置中这个名字已经指向另一来源，例如源码 checkout。已发布的 `0.2.19`、`0.2.20` 及准备中的 `0.2.21` 都保留此保护：只接续可核验的受管来源与 receipt，不自动把开发登记改成 npm 安装。移到中性 cwd 可避开项目级发现，但不会移除已有持久登记，`--yes` 也不绕过归属检查。

在自己信任的仓库外目录，可只读查看登记；输出中的本机路径或来源信息不要原样公开：

```sh
codex plugin marketplace list --json
```

已有个人源码注册时先保留它；普通 npm 安装与用户验收另用没有这项开发登记的干净普通用户配置。临时 CLI 配置不能替代独立 GUI／登录环境，本地候选包也不是个人来源冲突的自动解决办法。若以后选择切换个人开发注册，需要先明确要保留的来源、插件、录制和配置，以及重启与登录环境影响，再由用户授权处理该项登记；不要为解决冲突删除整个 CODEX_HOME、录制或无关配置。正式入口仍使用已发布的 npm 包。

## 检查与卸载

```sh
npx dsh-trace-extension setup --dry-run
npx dsh-trace-extension doctor
npx dsh-trace-extension uninstall
```

`--dry-run` 不创建持久配置或复制插件到用户目录。`doctor` 只读检查配置和文件，不把已安装或旧录制当作原生验收。`--yes` 可用于无交互终端，但不会绕过无关配置或文件修改冲突。`--json` 输出结构化结果。

`--codex-home`、`--trace-root` 可指定目录。默认创建供后续登录使用的录制 LaunchAgent；`--no-persist` 只配置当前登录会话。首次仍需重启 Codex，登录时与自动启动 Codex 的先后关系也需要实际验证。

## 终端动效（0.2.21 准备发布）

以下交互将随 `0.2.21` 的实际安装器交付；当前 npm 默认版本 `0.2.20` 尚不包含这版界面。

交互终端默认只展示实际发生的检查、安装、校验步骤及下一步，每个输出段落都以小表情开头，减少空行。已知修复原因、登录设置和内部路径收进详情；仅实际启用录制或改变登录设置时，在确认前保留一行影响提示。自定义录制目录、改变后的目标目录、未知操作和错误始终可见。确认时输入 `d` 展开完整计划，仍需明确输入 `y` 才会安装；`--verbose` 直接展示详情，`--dry-run` 保留完整计划。无需修改时不再询问是否应用。

`--no-animation` 或 `DSH_TRACE_NO_ANIMATION=1` 关闭动态刷新，`NO_COLOR` 单独关闭颜色。重定向输出、`TERM=dumb`、CI 和 `--json` 使用原有静态输出，不写动效控制码。

发布前可在源码工作区试看合成片段：

```sh
npm run demo:installer
npm run demo:installer -- --scenario repair
npm run demo:installer -- --scenario unchanged
npm run demo:installer -- --scenario error
npm run demo:installer -- --verbose
```

预览仅播放合成步骤，不调用安装器、不读取个人配置、不修改安装或录制。预览中的等待用于观察表情和光点，实际安装不会为了播放动效而延时。这个预览脚本只作为源码开发工具，不包含在 npm 发行包中；发行包入口仍为 `setup`、`doctor` 和 `uninstall`。

## 更新与恢复（0.2.20 起）

安装、更新和可确认归属的修复使用同一入口：

```sh
npx dsh-trace-extension@latest setup --dry-run
npx dsh-trace-extension@latest setup
```

更新基线从正式 npm `0.2.19` 开始。首发 receipt 必须匹配已发布的 payload 身份；后续 receipt 保存原始 manifest 与配置模板以核验归属。历史开发来源、未知字段、内容修改、降级或同版本不同包内容会停止，不自动接管。

更新先准备新的持久 bundle，保留旧 bundle；相同发行包重复安装复用现有内容。受管来源或 Codex 安装缓存中的已知缺失文件可以从相同包补齐。已有文件内容被修改时保留并停止，不能把用户编辑与文件损坏混为一谈。缓存中的额外文件不被修复操作删除；版本更新和卸载遇到未知额外内容会要求先复核。只有与当前 Python、已校验源码完全对应的生成 bytecode 才识别为运行缓存。

从公开 `0.2.19` 更新时，若旧稳定来源缺少插件文件，但首发身份、receipt、来源现存内容、安装归属与完整旧缓存均可独立核验，新助手会在同一计划和事务中从旧缓存补回确知的旧字节，再继续更新。它不使用新包内容冒充旧文件，也不会自动联网获取旧包。缓存不足或被修改时停止，要求从独立核验的原始归档或备份恢复明确缺失的路径后，再重试当前助手；公开 `0.2.19` 的原 setup 不具备这项修复能力，不能把重跑它当作恢复步骤。

安装在修改前记录私有 `operation.json`，使用同 profile 的操作锁防止并发修改。已知中断后的同版本重试会先展示恢复计划，按记录恢复仍匹配的写入，再继续安装；更新失败保留旧资源，或保留明确的恢复记录。doctor 会报告未完成操作及应重试的版本。恢复记录、配置或环境被外部修改时停止，保留文件供复核，不盲删状态文件。

Python 的绝对路径属于受管安装身份。旧解释器路径不可用时，可以在 PATH 中提供有效 Python 3.9+，或用 `DSH_TRACE_PYTHON=/absolute/path/to/python3` 选择解释器，再运行新助手的 setup。它会核对旧来源并重新固定受管副本与安装缓存中的启动路径，保留旧 bundle。无需手工改 receipt；未知或被编辑的来源仍要求先复核。

操作锁位于 `~/Library/Caches/dsh-trace-extension/`，按 CODEX_HOME 区分。恢复记录、备份和绝对路径属于本地私有资料，不应提交或上传。助手不为历史开发安装补做迁移。

## doctor 的检查范围

doctor 分别报告配置、受管来源、Codex 安装缓存和后端探测，原生状态始终单独标为未验证。安装缓存检查会核对当前启用版本的实际文件，而不仅依赖 CLI 的 installed/enabled 元数据。本次运行的 npx 包版本与已安装版本不同，本身不代表安装损坏。

仅在受管内容、安装缓存和解释器满足检查条件时，才将经过哈希复核的代码复制到私有临时目录，以空 HOME、空录制目录执行 MCP initialize/tools-list。准备文件有数量和 128 MiB 总量上限；后端子进程限制为 5 秒和合计 128 KiB 输出，超限会停止本探测创建的进程组。它不会执行被修改或来源不明的缓存文件，不读取真实聊天，也不把返回工具列表当作原生侧栏通过。无法安全确定时显示 unknown 或 not-run 及原因。

缺失文件可查看 setup 计划；被修改或未知的文件先保留并复核。不要为绕过保护直接删除录制、整个 CODEX_HOME 或恢复记录。未完成 setup 应先按 doctor 给出的原操作版本恢复，再卸载。

## 稳定的本地副本

Codex 登记的来源位于 `$CODEX_HOME/dsh-trace-extension/marketplace`，而不是 npx 缓存。清空 npm 缓存不会删除安装好的插件。受管副本使用已检测的 Python 绝对路径，减少 GUI PATH 差异。

重复安装校验自身文件后复用；同名陌生来源或被用户修改的受管内容会保留并报错。已知发行版的更新、修复与恢复规则见上文；公开前开发安装不构成迁移契约。

卸载保留录制和无关配置。仍被 Codex 来源登记引用的稳定副本保留，避免产生悬空路径。安装过程中如果已经尝试登记来源，后续失败也会保留可验证的副本并说明状态。

录制可能包含提示词、代码、工具输出和敏感值，分享前阅读[安全说明](../.github/SECURITY.md)。

## 维护者打包和验收

根开发包保持 `private: true`。独立 npm 发行包从显式白名单生成，只包含 CLI、安装与校验模块、bundle manifest、marketplace、已构建插件、图标和许可证。

```sh
npm ci
npm run build
npm run test:npm
```

这些检查属于维护者内部校验。`test:npm` 使用本地 tarball、临时 HOME 与 fake Codex/launchctl，检查缓存独立、重复安装、doctor 和卸载，不替代真实 npm 获取、原生侧栏或用户原样验收。核对并冻结源码、版本和生成物后，再生成一个实际发行归档：

```sh
npm run package:npm
npm pack ./dist/npm/dsh-trace-extension --ignore-scripts --pack-destination dist/npm --json
```

记录该归档的提交、版本、SHA-256/integrity、文件表和许可，排除私有工作资料。后续预发、验收和正式推广使用同一份归档；内容改变须重新冻结与核对，已公开的版本不能替换字节。

包无依赖、无 install/postinstall 脚本，不包含测试、用户配置、录制、日志或整个源仓库。安装仅在用户显式执行 `setup` 时进行。

### 试用本地候选包

本节仅供维护者内部 CLI 校验；本地 tgz 不替代发布流程、真实 npm 验证或交给用户的原样验收。

`npx dsh-trace-extension setup` 使用 npm 发布包，切换工作树分支不会让它运行本地源码。目前 npm 默认版本为 `0.2.20`，本地正在准备发布 `0.2.21`；试用后者需取得已核对的 `.tgz`，或按[维护者打包和验收](#维护者打包和验收)生成，再显式指定绝对路径。在自己信任的仓库外目录试跑；下面创建当前用户独占的临时 cwd，只生成计划：

```sh
# 替换为已取得或打包的候选文件绝对路径
dsh_candidate_tgz="/absolute/path/to/dsh-trace-extension-0.2.21.tgz"
(
  dsh_trial_root="$(mktemp -d)" || exit 1
  [ -n "$dsh_trial_root" ] || exit 1
  cd "$dsh_trial_root" || exit 1
  dsh_trial_root="$(pwd -P)" || exit 1
  [ -n "$dsh_trial_root" ] || exit 1
  mkdir -m 700 "$dsh_trial_root/home" || exit 1
  HOME="$dsh_trial_root/home" CODEX_HOME="$dsh_trial_root/codex" \
    npx --yes --offline --ignore-scripts --cache "$dsh_trial_root/npm-cache" \
    --package "$dsh_candidate_tgz" -- dsh-trace-extension setup --dry-run \
    --codex-home "$dsh_trial_root/codex" --trace-root "$dsh_trial_root/recordings"
)
```

这里 npx 可写临时缓存，安装助手只读检查计划；真实登录域若已有不同录制配置，仍会保留并拒绝。`--codex-home` 和临时 HOME 只分开 CLI 文件，不能替代原生 GUI／登录域隔离；不要直接去掉 `--dry-run` 当作隔离安装，`--no-persist` 也仍可能设置当前登录环境。已知发行版的更新归属从可核验的 npm `0.2.19` 受管安装开始；`0.2.21` 仍需记录本版实际覆盖的升级和验收范围，不能用本地候选的 CLI 结果证明原生侧栏或重新登录通过。

## 发行记录与后续发布

`dsh-trace-extension@0.2.19` 是 2026-11-17 发布的首个 npm 版本，包含已构建前端、Python 读取器、安装器、图标及许可证。此前的开发版本不构成发行或迁移契约。后续兼容性评估从 `0.2.19` 开始；发布下一版本前需要明确并验证升级行为。

`0.2.19` 已从公共 npm 仓库下载，在 macOS 的隔离 HOME / CODEX_HOME 中用真实 Codex CLI 验证全新安装、重复安装、doctor 和卸载。清空 npm 缓存后，已安装后端仍能提供工具和完整前端资源。这一轮隔离测试未修改个人 Codex 配置与登录环境；该轮证据不包含重启后的原生侧栏或再次登录时的启动顺序。

`0.2.20` 已于 2026-11-18 发布并设为默认 `latest`，从真实 npm 下载的归档与修复包哈希一致。经用户授权，个人配置已备份并切换至 npm 管理，README 原命令的交互安装和后端自检通过，原源码与录制保留。用户随后确认侧栏可正常打开，因此侧栏打开检查已验收；这项反馈不单独证明新录制生成、实时事件更新或重新登录后的行为。

`0.2.21` 正在准备发布，交付本次紧凑机器人终端交互、详情展开和动效开关；合成预览脚本仍仅为源码开发工具。本版需单独核对发行归档和实际测试范围，不能把 `0.2.20` 的侧栏反馈直接登记为 `0.2.21` 的全部原生验收。

公开预发前核对真实 tarball 内容、完整性和已有内部验证，并确认预发已获明确授权；推广到默认入口前核对真实 npm 获取、原生验收结果和推广授权。直接发布已审阅的 `.tgz`，不要发布根开发包；发布账号须具备 npm 权限和有效认证。

### 预发、推广与用户原样验收

可选的正式发版前验证按以下顺序进行。每个 npx 入口都从自己信任的仓库外目录运行；内部本地包测试不能跳过后面的真实 npm 和用户验收。

1. **内部校验**：维护者复核同一归档；临时 CLI 配置和私有 launchctl shim 的结果只覆盖其声明范围。
2. **单独授权公开预发**：取得明确授权后，可执行 `npm publish /absolute/path/to/dsh-trace-extension-0.2.21.tgz --tag next --access public --ignore-scripts`。`next` 的包可被任何人下载，版本内容随即公开且不可替换；默认 `latest` 保持原版。发布到 `next` 不是私有预览，也不是用户原样验收。
3. **真实 npm 与原生验证**：交付／验收会话通过 `npx dsh-trace-extension@next setup` 从真实 npm 安装，在独立 macOS／Codex 测试身份核对下载归档、真实侧栏、完全重开和重新登录后的录制。新任务应对应当前聊天并持续显示步骤；不能用本地 tgz、仅改 CODEX_HOME 或模拟登录域证明这些结论。
4. **推广，再交用户**：上述检查通过且正式推广也已获明确授权后，才执行 `npm dist-tag add dsh-trace-extension@0.2.21 latest`，推广同一已验版本，不重新打包。随后在干净普通用户配置中按 README 原样执行 `npx dsh-trace-extension setup`，实际安装、重开、跑新任务、打开侧栏，核对当前聊天与持续步骤。`@next` 的预发验证不能代替这一步。

发布前重新只读核对版本和标签，等待实际归档可从 npm 下载并比对完整性。发 `next` 与切 `latest` 都须处于明确授权范围内；授权可以预先覆盖不同阶段，但不能从预发自动延伸到正式推广，当前说明也不构成执行授权。预发和公开发布都不会消除个人已有的源码 `rollout-local` 冲突，源码开发身份不作为新用户验收起点。

## REA 参考

参考 [morluto/rea](https://github.com/morluto/rea) 的自包含 npm 分发，以及 setup/doctor/uninstall、计划确认、归属保护和文件完整性检查。研究基线为 [`552d1c7`](https://github.com/morluto/rea/tree/552d1c7108b99d1c9ec15d8b629ae07dc56d4714)，[MIT 许可](https://github.com/morluto/rea/blob/552d1c7108b99d1c9ec15d8b629ae07dc56d4714/LICENSE)。本项目为独立实现，没有复制 REA 代码。
