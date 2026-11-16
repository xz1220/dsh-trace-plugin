# Security and privacy

Codex Trace processes local recordings that can contain system instructions, credentials, private code, file paths, tool output, and images. Treat an entire recording as sensitive until you have reviewed it.

## Report a vulnerability

Use [GitHub private vulnerability reporting](https://github.com/xz1220/dsh-trace-plugin/security/advisories/new) if it is enabled for the repository. If that route is unavailable, open an issue containing only a request for a private contact channel, or use a private contact method listed on [the maintainer's profile](https://github.com/xz1220). Do not publish a live trace, credential, bootstrap URL, or exploit containing another person's data.

Include the affected version, operating system, relevant Codex version, impact, and minimal reproduction using synthetic data. Redact paths and secrets. We will coordinate disclosure once the issue and a repair are understood; response times are not guaranteed for this volunteer-maintained project.

## Supported versions

Security fixes target the latest release on `main`. Older 0.2.x versions are not maintained separately. Update to the latest release before reporting an already-fixed issue. A version in an installed package can differ from an already-open Codex connection.

## What the reader accesses

The catalog reads official trace bundles from the default `$CODEX_HOME/rollout-traces` directory, `CODEX_ROLLOUT_TRACE_ROOT`, and explicitly registered roots. `$CODEX_HOME` defaults to `~/.codex`. It does not use ordinary session archives to invent missing recording data.

Recordings are read-only. `add_rollout_directory` and the `--register` command add a root to `$CODEX_HOME/rollout-viewer/config.json`; this is a configuration write, and it expands which local recordings the reader can discover. The config directory and newly written config use restrictive permissions where supported by the operating system.

The recording helper creates a recording directory and starts Codex with tracing enabled. Its macOS desktop option changes an environment variable for subsequently launched apps in the current login session. Recording is a separate action from viewing.

## Existing defenses

- Identifiers and payload paths are validated; traversal and absolute payload paths are rejected.
- Recording-file reads reject symlinks and files with multiple hard links, and require ordinary files.
- Event logs, payloads, request bodies, pages, and caches have explicit limits.
- Detailed tools are marked app-only, and the model-facing launch tool returns launch metadata rather than prompt bodies.
- The optional preview binds to `127.0.0.1`, uses a random bootstrap secret and an authenticated HttpOnly, SameSite cookie, and checks origins on API requests.

These measures are defense in depth. The server runs with the user's permissions. It does not sandbox hostile local processes, guarantee atomic protection against concurrent file-system replacement, or control what the Codex host does with received data. MCP visibility hints depend on the host enforcing them.

## Network and sharing

The reader has no analytics, recording upload, model API, or remote-service integration. Native operation transports data through the local host's MCP connection. Preview operation serves data over loopback HTTP. The browser may open an external link when you follow it; copying text, exporting images, or sharing screenshots also moves data beyond the viewer.

The preview's bootstrap URL is a credential. Do not publish it, expose the preview through port forwarding, or run it as a public web service. Stop the server after use. Do not assume loopback cookies isolate the app from every other local process.

Use synthetic recordings in issues, tests, and screenshots. Remove credentials from the original recording before sharing any copy; replacing a visible label in a screenshot does not sanitize the source trace. If an actual credential was exposed, revoke it at its source.
