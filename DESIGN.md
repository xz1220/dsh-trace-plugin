# Design system

The developer reads a trace next to a chat in an ordinary daytime desktop workspace. Default to a light neutral theme, with a dark alternative and compact/comfortable density controls.

- System sans for UI, system monospace for code and timing.
- UI body 13 px / 20 px; title 18 px / 26 px; code 12 px / 19 px.
- 4 px spacing scale; 6–10 px control radius; 1 px neutral dividers.
- Blue: model request and selection. Teal: tools. Amber: incomplete evidence. Red: failures. Status always includes text.
- Timeline above a split event list and inspector. Below 760 px, the inspector replaces the list with an explicit Back action.
- Long request content lives in collapsible source sections. Raw request and resolved context are separate views.
- Prototype data is synthetic and labelled throughout. UI latency targets are design goals, not measured production promises.
