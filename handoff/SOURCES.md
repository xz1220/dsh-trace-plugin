# 固定版本与研究来源

这些是本次工作实际引用的版本与资料，不表示未来版本仍完全相同。

## 官方 Codex

- 测试 CLI：0.163.0。
- 固定源码 commit：`83086188ae0614bd882818ff1aa23f3194962012`。
- [rollout-trace 实现](https://github.com/openai/codex/tree/83086188ae0614bd882818ff1aa23f3194962012/codex-rs/rollout-trace)。
- [inference 录制代码](https://github.com/openai/codex/blob/83086188ae0614bd882818ff1aa23f3194962012/codex-rs/rollout-trace/src/inference.rs)。
- [官方插件面板扩展文档](https://developers.openai.com/plugins/build/extensions)。
- [App Server 文档](https://learn.chatgpt.com/docs/app-server)。早期审计验证了分页接口；生产插件当前直接读取 rollout-trace。
- `local-context/experiments/feasibility/schema/` 是本机 CLI 导出的协议 schema；不是账户数据。

## DeepSeek Harness

- 仓库：`deepseek-ai/deepseek-harness`。
- 固定 commit：`e8f7b93a344964de3dca1ace9e72b6e4d6de87cb`。
- [轨迹组件源码](https://github.com/deepseek-ai/deepseek-harness/tree/e8f7b93a344964de3dca1ace9e72b6e4d6de87cb/packages/client/ui-trajectory)。
- [主题源码](https://github.com/deepseek-ai/deepseek-harness/tree/e8f7b93a344964de3dca1ace9e72b6e4d6de87cb/packages/client/ui-theme)。
- 15 个引用文件和 Git blob SHA 位于 `design/dsh-sources.json`，实际副本在 `design/dsh-source/`。构建器会校验并按需重新下载。
- `design/analysis-excerpts.json` 保存设计分析引用摘录。
- MIT 许可证和署名：`design/DSH-LICENSE.txt`、`design/DSH-NOTICE.md`；生产 HTML 内也保留许可证。

## 早期比较对象

- [icesixgod/codex-trajectory](https://github.com/icesixgod/codex-trajectory)：安装并测试了 1.1.0。它主动排除基础指令；在本机大量 session 文件下重复扫描关联关系，曾出现约 8 秒的读取延迟。
- [该项目的数据接口说明](https://github.com/icesixgod/codex-trajectory/blob/main/docs/interface.md)。这些是早期比较记录，本插件不依赖它。
- AgentsView、session-profiler、codex-history-viewer 等属于最初选型讨论。最终方向已经确定为本项目，不应重新回到推荐工具的阶段。

## 证据入口

- 早期数据/协议/DSH 可行性：`local-context/experiments/feasibility/evidence.json`。
- 第一次真实请求：`local-context/experiments/first-real-trace/verification.json`。
- 最新真实任务：`reports/real-task-validation.json`，以及 `local-context/validation/real-task/official-state.json`。
- 实际安装 v0.1.3：`reports/installed-validation.json`。
- 性能：`reports/performance.json`，明确限于本机后端测量。
- 完整公开讨论：`local-context/conversation-visible.md`。历史结论有修订，最终口径见 `HANDOFF.md`。
