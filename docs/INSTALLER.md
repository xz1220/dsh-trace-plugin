# 单命令安装助手

`dsh-trace-extension` 安装助手负责检查环境、安装现有 Codex 插件并配置录制。首版面向 **macOS 和 Codex**；Antigravity 等 Agent 尚未接入。

安装后仍需手动完全退出并重新打开 Codex。助手不会关闭应用，也不能给已经运行的 Codex 补开录制。

## 从私有仓库安装

需要以下环境：

- Python 3.9+，可通过 `python3` 启动。
- 支持 `plugin marketplace` 和 `plugin add` 命令的 Codex CLI。
- 已登录的 [GitHub CLI](https://cli.github.com/)，且当前账号可访问仓库；Codex 的 Git 下载同样需要仓库访问权限。

仓库目前为私有，推荐使用已认证的 `gh` 下载入口：

```sh
gh api --hostname github.com 'repos/xz1220/dsh-trace-plugin/contents/install.sh?ref=main' -H 'Accept: application/vnd.github.raw' | sh
```

入口脚本会将所选 ref 解析为一个 commit，从该 commit 下载安装助手并核对 Git blob SHA。新注册的插件来源也固定到该 commit；复用已登记来源时保留其原有配置。安装所用的仓库权限仍需由 GitHub 凭据提供。

先查看计划而不修改安装和录制配置：

```sh
gh api --hostname github.com 'repos/xz1220/dsh-trace-plugin/contents/install.sh?ref=main' -H 'Accept: application/vnd.github.raw' | sh -s -- --dry-run
```

`--dry-run` 仍需要下载助手到临时目录；它不是离线命令。

助手不会自动安装或升级 Python、Node.js 等运行时。安装已构建的插件不需要 Node.js、npm 或源码构建。

## 在已有源码目录中使用

在仓库根目录运行：

```sh
sh install.sh --dry-run
sh install.sh
```

安装助手内部完成 marketplace 注册、插件安装、录制目录创建和录制环境配置。已安装且启用的同项目插件会复用；此命令不是强制更新器，也不会修改 Git 全局认证。它会先显示操作计划；非交互运行需要显式传入 `--yes`，不会把没有终端当作同意。

```sh
sh install.sh --yes
```

安装成功后：

1. 手动完全退出并重新打开 Codex。
2. 执行一个新的任务。
3. 从聊天侧栏打开 **Codex Trace**，检查是否出现该任务的请求和工具记录。

项目名称为 `dsh-trace-extension`；当前发行包仍使用 `codex-dsh-trace@rollout-local`，界面入口仍显示 **Codex Trace**。安装助手保留这些已有标识。

## 检查与卸载

三个操作共用同一个入口：

```sh
sh install.sh setup --dry-run
sh install.sh doctor
sh install.sh uninstall --dry-run
sh install.sh uninstall
```

省略操作名时默认为 `setup`。也可以用前面的 `gh api ... | sh -s -- doctor` 方式运行检查。

`doctor` 用于检查安装和录制配置，并说明下一步需要重启、等待新任务还是修复配置。配置正确不等于正在运行的 Codex 已重载，也不等于一次真实任务已成功录制；最终以新任务和侧栏中的实际记录为准。

卸载不会删除录制文件。安装前已经存在、被助手复用的插件也不会被当作本次新安装内容删除。

## 常用选项

| 选项                        | 用途                                             |
| --------------------------- | ------------------------------------------------ |
| `--client codex`            | 选择当前唯一支持的 Agent；默认即为 Codex         |
| `--source <仓库或本地目录>` | 指定安装来源，默认使用项目仓库或当前源码目录     |
| `--ref <ref>`               | 选择远程来源的分支、tag 或 commit                |
| `--trace-root <目录>`       | 指定官方录制的保存目录                           |
| `--codex-home <目录>`       | 指定本次操作使用的 Codex 配置根目录              |
| `--dry-run`                 | 只显示检查结果和操作计划，不应用安装与录制配置   |
| `--yes`                     | 明确同意计划内操作，适合没有交互终端的运行环境   |
| `--json`                    | 输出结构化结果，便于脚本或 Agent 判断状态        |
| `--no-persist`              | 只配置当前登录会话，不创建供后续登录使用的启动项 |

## 后续登录与录制生效

默认设置当前登录会话的录制环境，并创建用户级 LaunchAgent，供后续登录时恢复该设置。使用 `--no-persist` 可关闭后者。

这不改变 Codex 的录制机制：Codex 必须在录制环境已就绪后启动。首次安装仍需完全退出并重开 Codex；登录时 LaunchAgent 与 Codex 自动启动的先后顺序也需要实机验证，不能将“已写入启动项”当成“所有后续启动都已录制”。

已有但未录制的执行无法补录。录制可能含提示词、代码、工具输出和敏感值，分享前请阅读 [安全说明](../.github/SECURITY.md)。

## 重复运行、失败和恢复

- **重复运行**：复用已经一致的安装和配置，避免重复添加启动项或覆盖最初备份。
- **归属保护**：同名文件或设置只有在助手能够确认归属时才会修改；用户自行创建或后续修改的内容会保留并报告。
- **有限回滚**：失败后只回滚本次由助手管理、且未被其他操作再次修改的文件。不会用旧备份整份覆盖 Codex 配置。
- **保留部分结果**：官方 Codex CLI 的步骤可能已经成功，之后的步骤仍可能失败。助手会如实报告已完成和未完成的内容，便于修复后重试，不将部分成功描述为全部成功。
- **保留录制**：检查、重复安装、恢复和卸载均不删除历史录制。

先运行 `doctor` 查看具体问题；需要重试时可先用 `setup --dry-run` 检查将要执行的操作。

## 公开仓库后的下载入口

匿名 `curl` 不会自动使用 Git 的认证凭据。当前私有仓库的 raw URL 不能作为匿名安装承诺。

仓库公开并验证下载链路后，才可提供以下可选入口：

```sh
curl -fsSL https://raw.githubusercontent.com/xz1220/dsh-trace-plugin/main/install.sh | sh
```

## REA 安装器参考

设计参考了 [morluto/rea](https://github.com/morluto/rea) 的安装器，研究基线为 commit [`552d1c7108b99d1c9ec15d8b629ae07dc56d4714`](https://github.com/morluto/rea/tree/552d1c7108b99d1c9ec15d8b629ae07dc56d4714)，使用 [MIT 许可](https://github.com/morluto/rea/blob/552d1c7108b99d1c9ec15d8b629ae07dc56d4714/LICENSE)。本项目安装助手为原创实现，没有复制 REA 代码。

主要借鉴：

- [安装入口](https://github.com/morluto/rea/blob/552d1c7108b99d1c9ec15d8b629ae07dc56d4714/install.sh)的截断保护、计划展示和交互终端判断。
- [配置流程](https://github.com/morluto/rea/blob/552d1c7108b99d1c9ec15d8b629ae07dc56d4714/src/application/SetupClientConfiguration.ts)的幂等、归属检查、备份与写后验证。
- [卸载流程](https://github.com/morluto/rea/blob/552d1c7108b99d1c9ec15d8b629ae07dc56d4714/src/application/Uninstall.ts)的受管范围和用户修改保留规则。
