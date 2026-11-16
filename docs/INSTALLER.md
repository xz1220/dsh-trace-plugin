# npx 安装助手

项目尚未正式 public，没有迁移用户。安装设计只面向当前的全新安装，不为历史开发版提供迁移或向后兼容路径。

> npm 包目前是已构建的候选，尚未公开发布。下面的短命令是正式发布后的入口，不能将未发布的包名当作已经可从 registry 安装。

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

## 稳定的本地副本

Codex 登记的来源位于 `$CODEX_HOME/dsh-trace-extension/marketplace`，而不是 npx 缓存。清空 npm 缓存不会删除安装好的插件。受管副本使用已检测的 Python 绝对路径，减少 GUI PATH 差异。

重复安装校验自身文件后复用；同名陌生来源或被用户修改的受管内容会保留并报错。开发期不同候选的清理与重建由开发者处理，不为其设计升级迁移策略。

卸载保留录制和无关配置。仍被 Codex 来源登记引用的稳定副本保留，避免产生悬空路径。安装过程中如果已经尝试登记来源，后续失败也会保留可验证的副本并说明状态。

录制可能包含提示词、代码、工具输出和敏感值，分享前阅读[安全说明](../SECURITY.md)。

## 维护者打包和验收

根开发包保持 `private: true`。独立 npm 发行包从显式白名单生成，只包含 CLI、两个安装器模块、bundle manifest、marketplace、已构建插件、图标和许可证。

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

## 首次公开发布

公开 npm 包将分发其中的已构建前端、Python 读取器、安装器、图标及许可证，GitHub 仓库本身可以继续私有。发布前检查真实 tarball 文件清单并取得明确授权；发布账号还需要具备 npm 权限和有效认证。当前只准备候选，不自动发布。

## REA 参考

参考 [morluto/rea](https://github.com/morluto/rea) 的自包含 npm 分发，以及 setup/doctor/uninstall、计划确认、归属保护和文件完整性检查。研究基线为 [`552d1c7`](https://github.com/morluto/rea/tree/552d1c7108b99d1c9ec15d8b629ae07dc56d4714)，[MIT 许可](https://github.com/morluto/rea/blob/552d1c7108b99d1c9ec15d8b629ae07dc56d4714/LICENSE)。本项目为独立实现，没有复制 REA 代码。
