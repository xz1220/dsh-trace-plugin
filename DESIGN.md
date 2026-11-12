# Design system

The developer reads a trace next to a chat in an ordinary daytime desktop workspace. The current mock uses original DSH theme and trajectory CSS pinned to e8f7b93a344964de3dca1ace9e72b6e4d6de87cb, with light/dark modes and narrow/expanded review surfaces.

- System sans for UI, system monospace for code and timing.
- Ledger and toolbar 12 px / 18 px; inspector tabs 13 px / 20 px; code 12 px / 19 px.
- 32 px toolbar, 50 px timeline, 30 px ledger rows, 34 px detail tab bar, 42 px inspector header. Dividers follow the original 0.5 px declarations.
- Neutral system records, brand-blue user records, green contextual inputs, mixed-purple model records, amber tools and softened amber nested calls. Red indicates failure; status also has text.
- Timeline above a split event ledger and inspector. Default detail width follows clamp(320px, 38%, 440px). Below 760 px, details become an overlay drawer, with an explicit close control. The narrow review mode reproduces this behavior.
- Long request content lives in collapsible source sections. Raw request and resolved context are separate views.
- Prototype data is synthetic and labelled throughout. UI latency targets are design goals, not measured production promises.
- The production sidebar uses 12 px outer gutters, a stable 72 px event column, and 44 px event badges. Ledger text and the timeline track start at 80 px; ledger and inspector headers are both 30 px high. Prompt headings use shared role, preview, inheritance, and character-count columns.

The earlier custom-palette review remains in rollout-viewer.html for comparison; codex-trajectory-dsh.html is the current DSH-based interactive mock.
