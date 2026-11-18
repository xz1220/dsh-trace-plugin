# dsh-trace-extension

Set up local DSH-style execution traces for coding agents.

```sh
npx dsh-trace-extension setup
```

The package contains the built plugin and its setup tools. Installation does not
require a GitHub account, repository access, a source checkout, or a frontend
build. It installs a stable local copy, so clearing the npm cache does not remove
the installed plugin.

The current integration is **macOS / Codex** and requires a compatible Codex CLI
and **Python 3.9+**. Other agents are not yet integrated.

Setup shows the files and settings it will change before asking for confirmation.
It enables local recording, which may contain prompts, code, credentials, and
tool results. Fully quit and reopen Codex afterwards, run a new task, then open
**Codex Trace** from the conversation's tools menu.

```sh
npx dsh-trace-extension setup --dry-run
npx dsh-trace-extension doctor
npx dsh-trace-extension uninstall
```

`--json` emits structured output. `--yes` accepts the displayed setup plan for
non-interactive use; it does not override ownership conflicts. `--codex-home` and
`--trace-root` select configuration and recording locations. `--no-persist`
configures only the current login instead of creating a login LaunchAgent.

Interactive terminals show a small trace bot alongside real installation steps.
`--no-animation` or `DSH_TRACE_NO_ANIMATION=1` uses static progress; `NO_COLOR`
disables color. Piped output, CI, `TERM=dumb`, and JSON results stay plain.

Setup is repeatable for its own installation and refuses to overwrite
unrecognized or edited managed resources. Uninstall preserves recordings and
unrelated configuration. The verified local marketplace source is retained while
Codex still has its registration, avoiding a dangling source path.

Login setup does not prove the running Codex process has inherited recording
settings; native readiness is checked with a new task. Login ordering with
automatically launched Codex still needs native verification.

The reader does not upload recordings or add telemetry. It presents data to the
local Codex host. Review data before sharing, copying, exporting, or following
external links.

Independently maintained; not an official OpenAI or DeepSeek product. Includes
MIT-licensed DeepSeek Harness components and the bundled dependencies' notices.
See `LICENSE` and `THIRD_PARTY_NOTICES.txt`.
