#!/usr/bin/env python3
"""Create a deterministic plugin ZIP with an explicit distribution allowlist."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "codex-dsh-trace"
FILES = (
    ".codex-plugin/plugin.json",
    ".mcp.json",
    "LICENSE",
    "README.md",
    "THIRD_PARTY_NOTICES.txt",
    "assets/icon.png",
    "assets/icon.svg",
    "assets/logo-dark.png",
    "assets/logo-dark.svg",
    "assets/logo.png",
    "assets/viewer.html",
    "server/_version.py",
    "server/bridge-harness.html",
    "server/bundle_index.py",
    "server/catalog.py",
    "server/main.py",
    "server/preview.py",
    "server/projection.py",
    "server/recorded_content.py",
    "server/recording.py",
    "server/store.py",
    "server/snapshots.py",
    "server/thread_index.py",
    "server/trajectory-locales.json",
)


def main() -> None:
    version = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
    manifest = json.loads((PLUGIN / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
    if manifest["version"] != version:
        raise SystemExit("Plugin version is stale; run npm run build.")
    # New backend modules must be consciously added to the distribution rather
    # than producing a ZIP that only fails after installation.
    runtime_files = {
        path.relative_to(PLUGIN).as_posix()
        for path in (PLUGIN / "server").rglob("*")
        if path.suffix in {".py", ".json", ".html"} and "__pycache__" not in path.parts
    }
    missing = runtime_files - set(FILES)
    if missing:
        raise SystemExit(f"Runtime files are absent from the package allowlist: {sorted(missing)}")
    for relative in FILES:
        source = PLUGIN / relative
        if source.is_symlink() or not source.is_file():
            raise SystemExit(f"Distribution file is missing or is a symlink: {relative}")
    output = ROOT / "dist" / f"codex-dsh-trace-{version}.zip"
    output.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=output.parent, suffix=".zip", delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with ZipFile(temporary_path, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
            for relative in sorted(FILES):
                source = PLUGIN / relative
                info = ZipInfo(f"codex-dsh-trace/{relative}", (1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                info.compress_type = ZIP_DEFLATED
                archive.writestr(info, source.read_bytes(), compresslevel=9)
        temporary_path.replace(output)
    finally:
        temporary_path.unlink(missing_ok=True)
    checksum = hashlib.sha256(output.read_bytes()).hexdigest()
    checksums = output.parent / "SHA256SUMS"
    checksums.write_text(f"{checksum}  {output.name}\n", encoding="utf-8")
    print(f"Packaged {output.relative_to(ROOT)} ({output.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
