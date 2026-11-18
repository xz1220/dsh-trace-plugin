<div align="center">

# Codex Trace

**Agent 卡住或结果出乎预期时，沿轨迹查看它收到什么、调用了什么。**

把 DeepSeek Harness（DSH）的时间轴、执行列表和详情查看带到 Codex 聊天侧栏。

[English](README.md) · [快速开始](#快速开始) · [如何工作](#如何工作) · [能看到什么](#能看到什么) · [FAQ](#faq) · [文档](#文档)

</div>

```sh
npx dsh-trace-extension setup
```

![Codex Trace 的时间轴、执行列表与详情面板](docs/images/trace-viewer.png)

_合成数据的本地预览，不含私人聊天。_

## 快速开始

### 运行要求

- **macOS / Codex**：客户端支持本地插件、MCP Apps 和官方 `rollout-trace` 录制。
- **Node.js** 与 npm/npx，用于运行安装助手。
- 可用的 **Python**（`python3`）及 PATH 中支持插件命令的 **Codex CLI**。Python 读取器无需额外 Python 包。

详细环境要求见[安装说明](docs/INSTALLER.md#用户入口)。

### 1. 安装

在自己信任的仓库外目录打开终端，运行：

```sh
npx dsh-trace-extension setup
```

包内包含已构建插件，无需 GitHub 登录、克隆源码或本地构建。助手展示文件与配置变更，确认后准备稳定的本地副本并配置录制。

如需先查看操作计划，可选运行 `npx dsh-trace-extension setup --dry-run`。

### 2. 重开 Codex 并运行新任务

完全退出并重新打开 Codex，再运行一个新任务。录制配置必须在 **Codex 新进程启动前**生效；打开查看器不会开启录制，过去的执行不能补录。

### 3. 打开聊天侧栏

从聊天右侧工具菜单选择 **Codex Trace**。面板会查找当前聊天的录制，并持续读取新事件。时间轴定位步骤，执行列表追踪调用，详情面板展开内容。

设置与排障帮助见[安装说明](docs/INSTALLER.md)。

## 如何工作

```text
Codex 官方录制 → 本地 Python 读取器 → Codex 侧栏中的 DSH 界面
```

Codex 负责录制，查看器读取官方录制包。支持的录制格式见[产品说明](docs/PRODUCT.md#compatibility)。查看器不会修改录制；安装与显式登记录制目录会写入本地配置。

读取器没有主动上传轨迹、统计埋点或远程服务集成。原生模式把内容交给本地 Codex 宿主展示；可选预览通过带认证的本机回环 HTTP 提供数据。宿主如何处理收到的数据仍由宿主决定。

录制可能含提示词、工具输出、私有代码、图片和凭据。复制、导出或分享前请阅读[安全与隐私](.github/SECURITY.md)。

## 能看到什么

假设你让 Agent 修复一个失败的测试：先在**时间轴**定位等待发生的片段，在**执行列表**找到读文件和运行测试的调用，再打开**详情**核对参数、返回以及模型收到的上下文。

| 想核对的问题               | 查看位置与记录                                          |
| -------------------------- | ------------------------------------------------------- |
| 执行到了哪一步？           | 时间轴和列表中的请求、嵌套工具调用与返回。              |
| 工具实际做了什么？         | 调用详情中的参数、结果与支持的已录制图片。              |
| 模型收到了什么？           | 分别查看还原的完整上下文、实际增量请求和原始响应 JSON。 |
| 时间花在哪里？             | 录制中可用的请求和工具耗时。                            |
| 任务恢复或压缩后怎样接续？ | 已有历史、分叉与压缩记录及其来源。                      |

完整上下文基于已有录制还原。未捕获的文字或图片、不透明的压缩内容、缺失耗时会明确保留为不可用；这些记录提供可见执行依据，不代表模型的全部内部思考。

## FAQ

<details>
<summary><strong>rollout-local 来源冲突怎么办？</strong></summary>

先只读查看当前来源：

```sh
codex plugin marketplace list --json
```

如果冲突来自临时项目发现，在信任的仓库外目录重试可能解决；切换目录不会移除持久登记。安装器会保留已有来源并停下，请保留原注册、配置和录制，按[来源冲突排障](docs/INSTALLER.md#rollout-local-来源冲突)处理，不要强删或覆盖。

</details>

<details>
<summary><strong>侧栏为空，或缺少部分内容？</strong></summary>

确认录制配置在 Codex 启动前生效，且录制属于当前聊天。空的续接录制会继续等待。查看器只展示实际录制的内容，无法补回缺失证据；格式不支持或超过限制时会明确报错。当前事件日志上限为 256 MiB，单个 payload 为 64 MiB。

</details>

<details>
<summary><strong>如何检查或卸载助手管理的安装？</strong></summary>

```sh
npx dsh-trace-extension doctor
npx dsh-trace-extension uninstall
```

doctor 只读检查配置和文件。卸载保留录制和无关配置。已安装文件与运行中的面板可能不同步，重开客户端后再核对界面。更多帮助见[安装说明](docs/INSTALLER.md)。

</details>

## 文档

- [安装与排障](docs/INSTALLER.md)
- [使用说明](docs/PRODUCT.md) · [工作原理](docs/ARCHITECTURE.md)
- [数据使用与分享](.github/SECURITY.md)
- [项目路线图](docs/ROADMAP.md)

## 参与贡献

通过 [GitHub Issue / PR](.github/CONTRIBUTING.md#issues-and-proposals) 提供合成复现或聚焦的改进。较大改动先讨论，维护者根据范围与证据安排处理，不承诺固定回复或修复时限。

[贡献指南](.github/CONTRIBUTING.md)包含开发准备与检查，[源码安装和手动录制](.github/CONTRIBUTING.md#source-installation-and-manual-recording)保留开发用法。在源码目录运行 `npm run demo` 可查看隔离合成录制，不读取个人 Codex 数据。

## 来源与许可

本项目独立维护，**不是 OpenAI 或 DeepSeek 官方产品**。界面使用 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)（DSH）MIT 组件，适配记录见 [vendor/dsh/PATCHES.md](vendor/dsh/PATCHES.md)。

本项目使用 [MIT 许可](LICENSE)，发行包附带 `LICENSE` 与第三方许可说明。
