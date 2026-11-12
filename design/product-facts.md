# Verified context

- Official Codex CLI 0.163.0 contains optional rollout-trace capture and trace-reduce.
- A real controlled test captured two model requests and one nested exec_command with millisecond execution bounds.
- WebSocket continuation requests can be incremental; a full-context viewer must follow the prior response chain.
- Official MCP Apps extension metadata supports thread entrypoints in a conversation panel.
- DSH ui-trajectory is MIT licensed. This mock references its information architecture; it does not copy implementation code or imply affiliation.

Sources:
- https://github.com/openai/codex/tree/83086188ae0614bd882818ff1aa23f3194962012/codex-rs/rollout-trace
- https://github.com/deepseek-ai/deepseek-harness/tree/e8f7b93a344964de3dca1ace9e72b6e4d6de87cb/packages/client/ui-trajectory
- https://developers.openai.com/plugins/build/extensions

All visible mock messages are authored for this prototype. No private session transcript or prompt is embedded.
