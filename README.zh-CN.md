# Codex Trace

在 Codex 聊天侧栏查看已录制的模型请求、嵌套工具调用、压缩记录和执行耗时。

[English](README.md) · [参与开发](.github/CONTRIBUTING.md) · [架构](docs/ARCHITECTURE.md) · [安全与隐私](.github/SECURITY.md)

![Codex Trace 展示合成录制数据](docs/images/trace-viewer.png)

_截图来自使用合成数据的本地预览，不含私人聊天，也不代表原生 Codex 安装验收。_

## 能做什么

- 自动打开当前聊天的录制，并持续读取新事件。
- 用 DSH 时间轴和执行列表查看过程，支持折叠、搜索和详情面板。
- 对比还原的完整上下文、实际发送的增量请求与原始响应 JSON。
- 追踪嵌套调用、录制时的子工具声明和工具结果，包括已录制的图片。
- 在任务恢复、分叉和压缩后保留已有历史及来源。
- 增量索引、虚拟列表和按需读取详情，减少大录制的加载开销。
- 跟随宿主主题和语言。上游控件支持八种语言，Codex 扩展文案目前使用中文或英文回退。

## 运行要求

- 支持本地插件、MCP Apps 和官方 `rollout-trace` 录制的 Codex 客户端。兼容性取决于客户端和录制格式。
- 可通过 `python3` 启动的 **Python 3.9+**，无需安装 Python 依赖。
- 从源码构建或开发需要 **Node.js 20.19+** 和 npm。已构建的插件运行时不需要 Node.js。

已在 macOS arm64 做本地检查。最初集成使用 Codex CLI 0.163.0；这是历史测试基准，不是最低版本保证。CI 在 Ubuntu 检查读取器与构建；Linux 和 Windows 尚未完成原生 Codex 集成验证。目前支持录制格式 **schema 1 和 2**。

## 安装

```sh
codex plugin marketplace add xz1220/dsh-trace-plugin
codex plugin add codex-dsh-trace@rollout-local
```

仓库已包含构建好的前端，安装时无需 Node.js、npm 或手动克隆源码。如果仓库仍为私有，你的 Git 凭据需要有仓库访问权限。

在聊天右侧工具菜单中打开 **Codex Trace**。新安装后若入口未出现，打开一个新聊天。

macOS 的单命令安装、配置检查与卸载方式见[安装助手说明](docs/INSTALLER.md)。

## 更新

```sh
codex plugin marketplace upgrade rollout-local
codex plugin add codex-dsh-trace@rollout-local
```

如果之前登记的是本地源码目录，先重新执行上面的两条安装命令，将 marketplace 切换到 Git 来源。

更新后完全退出并重新打开 Codex，使后端与界面资源重新加载。仅重新打开面板可能仍使用旧版。为兼容已有安装，marketplace 标识保留为 `rollout-local`。

## 从源码构建

用于开发或通过本地 marketplace 安装：

```sh
git clone https://github.com/xz1220/dsh-trace-plugin.git
cd dsh-trace-plugin
npm ci
npm run build
codex plugin marketplace add "$PWD"
codex plugin add codex-dsh-trace@rollout-local
```

在聊天右侧工具菜单中打开 **Codex Trace**。新安装后若入口未出现，重新打开面板或重启 Codex。不同 Codex 版本的菜单和插件命令可能有所不同。

仓库名为 `dsh-trace-plugin`，插件标识为 `codex-dsh-trace`，展示名称为 **Codex Trace**。原有 `rollout-viewer` MCP 标识与配置保留兼容，见[架构说明](docs/ARCHITECTURE.md#compatibility-identifiers)。

## 开启录制

必须在 **Codex 进程启动前**开启录制，无法补录已经发生的聊天。

启动新的 CLI 进程：

```sh
CODEX_ROLLOUT_TRACE_ROOT="$HOME/.codex/rollout-traces" codex
```

也可以录制一次 CLI 任务：

```sh
CODEX_ROLLOUT_TRACE_ROOT="$HOME/.codex/rollout-traces" codex exec --ephemeral "你的任务"
```

macOS 桌面端可为当前登录会话中后续启动的应用设置环境变量：

```sh
mkdir -p -m 700 "$HOME/.codex/rollout-traces"
launchctl setenv CODEX_ROLLOUT_TRACE_ROOT "$HOME/.codex/rollout-traces"
```

随后完全退出并重新打开 Codex。注销系统后需要重新执行。关闭桌面录制可运行 `launchctl unsetenv CODEX_ROLLOUT_TRACE_ROOT` 并重启 Codex。这些命令不会关闭应用。源码仓库也提供 `scripts/record.py` 作为录制辅助脚本。

在源码目录中登记其他录制目录：

```sh
python3 plugins/codex-dsh-trace/server/main.py --register /absolute/path/to/recordings
```

## 数据与隐私

插件读取默认目录、`CODEX_ROLLOUT_TRACE_ROOT` 和手动登记目录中的官方录制，不用普通会话日志代替。登记目录只会写入 `$CODEX_HOME/rollout-viewer/` 下的小型配置文件，默认位置是 `~/.codex/rollout-viewer/`；不会修改录制。

读取器没有上传、统计埋点或远程服务集成。录制内容交给本地 Codex 应用展示；可选预览通过带认证的 loopback HTTP 提供同一份数据。录制可能含密钥、私有代码、提示词和图片。分享截图、复制内容、导出图片或打开外部链接前，请先阅读[安全说明](.github/SECURITY.md)。

## 常见问题

**侧栏没有内容。** 确认 Codex 启动前已经开启录制，且录制属于当前聊天。打开查看器不会自动开启录制。任务恢复后若新录制暂时为空，界面会继续等待。

**安装后仍像旧版。** 安装文件与正在运行的客户端连接可能不同步。更新后完全退出并重新打开 Codex；安装成功不等于旧面板已经重载。

**提示格式不支持或超过大小限制。** 当前支持 schema 1/2，事件日志上限 256 MiB、单个 payload 上限 64 MiB。超过限制会明确报错。聊天合并视图超过上限时，仍可通过 API 分别查看单份录制。

**缺少历史文字、图片或耗时。** 查看器只展示实际录制的证据。加密压缩项、未捕获图片、缺失的续接上下文和未录制的生成耗时无法可靠还原。

## 参与开发

```sh
npm ci
npm run build
npm test
```

运行 `npm run demo` 可打开隔离的合成录制，不读取个人 Codex 数据。

先在本页了解安装与使用，再按[贡献指南](.github/CONTRIBUTING.md)完成开发准备、检查并找到要修改的目录。修改读取器或界面时阅读[架构说明](docs/ARCHITECTURE.md)；具体行为约束和后续计划见[产品说明](docs/PRODUCT.md)与[路线图](docs/ROADMAP.md)。

## 致谢与许可

本项目独立维护，**不是 OpenAI 或 DeepSeek 官方产品**。界面使用固定版本的 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) MIT 组件，来源及适配记录见 [vendor/dsh/PATCHES.md](vendor/dsh/PATCHES.md)。DSH 指该上游项目。

本项目代码使用 MIT 许可，见 [LICENSE](LICENSE)。构建的插件包包含 `LICENSE` 和 `THIRD_PARTY_NOTICES.txt`。
