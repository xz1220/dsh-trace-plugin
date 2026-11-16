# Historical synthetic design studies

This directory preserves the source and generated output of early interface prototypes and a pinned DSH design-system study. All demonstration data is synthetic. These pages do not read local Codex sessions or start model calls.

They are reference material, not the runtime UI or evidence that a native Codex installation has been verified. Current behavior and design live in [docs/PRODUCT.md](../docs/PRODUCT.md) and [docs/DESIGN.md](../docs/DESIGN.md).

Optional build targets:

```sh
npm run build:design
npm run build:analysis
npm run build:mock
```

The analysis/mock builders may fetch the pinned upstream source cache; normal plugin builds use the checked-in vendor source. Study attribution is in [DSH-NOTICE.md](DSH-NOTICE.md) and [DSH-LICENSE.txt](DSH-LICENSE.txt). Downloaded source caches and local screenshots are ignored.
