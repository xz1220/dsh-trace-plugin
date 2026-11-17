# Roadmap

The GitHub repository became public on 2026-11-16. The first npm release,
[`dsh-trace-extension@0.2.19`](https://www.npmjs.com/package/dsh-trace-extension/v/0.2.19),
was published on 2026-11-17. Do not add migration paths for earlier internal
development versions. Use `0.2.19` as the baseline for future compatibility
decisions, and define and verify upgrade behavior before the next release.

This is a direction for future work, not a release schedule. Small reproducible issues and focused contributions are welcome.

- **Native compatibility:** document tested Codex client versions and verify Linux/Windows integrations before claiming full platform support.
- **Reproducible UI checks:** expand synthetic scenarios for startup, resumed history, fork/compaction, search, images, and narrow layouts; keep native-host acceptance separate.
- **Accessibility:** expand the automated axe checks and review keyboard navigation, focus restoration, screen-reader labels, and reduced-motion behavior manually.
- **Localization:** translate the shared Codex-specific UI strings and structured errors beyond the current Chinese/English fallback.
- **Release experience:** validate the opt-in Release Please flow on real releases and keep generated assets reproducible across toolchain updates.
- **Maintenance:** preserve bounded caches and snapshot reads, measure realistic polling/body loads, and review upstream DSH updates with documented hashes and notices.

The current data contract is read-only trace inspection, apart from explicit catalog registration. A recording editor, general session-history browser, or hosted trace-sharing service would require a separate product and security design.
