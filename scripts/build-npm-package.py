#!/usr/bin/env python3
"""Assemble a self-contained npm candidate from the audited plugin ZIP allowlist."""

import hashlib
import importlib.util
import json
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
NAME = "dsh-trace-extension"


def main():
    spec = importlib.util.spec_from_file_location(
        "plugin_package", ROOT / "scripts/package-plugin.py"
    )
    plugin_package = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(plugin_package)
    plugin_package.main()
    version = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
    source = ROOT / "packages" / NAME
    destination = ROOT / "dist/npm" / NAME
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        raise SystemExit("Refusing a symlinked npm build destination.")
    if destination.exists():
        marker = destination / ".build-info.json"
        try:
            owned = json.loads(marker.read_text(encoding="utf-8")).get("name") == NAME
        except (OSError, ValueError):
            owned = False
        if not owned:
            raise SystemExit("Preserving an unrecognized npm build destination.")
    with tempfile.TemporaryDirectory(prefix=".npm-build-", dir=destination.parent) as temporary:
        stage = Path(temporary) / NAME
        stage.mkdir()
        metadata = json.loads((source / "package.json").read_text(encoding="utf-8"))
        metadata.pop("private", None)
        metadata["version"] = version
        (stage / "package.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        shutil.copytree(source / "bin", stage / "bin")
        (stage / "bin/dsh-trace-extension.mjs").chmod(0o755)
        shutil.copy2(source / "README.md", stage / "README.md")
        shutil.copy2(ROOT / "LICENSE", stage / "LICENSE")
        shutil.copy2(
            plugin_package.PLUGIN / "THIRD_PARTY_NOTICES.txt", stage / "THIRD_PARTY_NOTICES.txt"
        )
        payload = stage / "payload"
        with ZipFile(ROOT / "dist" / f"codex-dsh-trace-{version}.zip") as archive:
            for member in archive.infolist():
                relative = PurePosixPath(member.filename)
                if (
                    relative.is_absolute()
                    or ".." in relative.parts
                    or relative.parts[0] != "codex-dsh-trace"
                ):
                    raise SystemExit("Unexpected plugin ZIP member.")
                target = payload / "plugins" / Path(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(member))
        catalog = payload / ".agents/plugins/marketplace.json"
        catalog.parent.mkdir(parents=True)
        catalog.write_bytes((ROOT / ".agents/plugins/marketplace.json").read_bytes())
        files = {
            f.relative_to(payload).as_posix(): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in sorted(payload.rglob("*"))
            if f.is_file()
        }
        manifest = {
            "format": 1,
            "name": NAME,
            "version": version,
            "repository": "xz1220/dsh-trace-plugin",
            "files": files,
        }
        (payload / "bundle-manifest.json").write_text(
            json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        helper = payload / "installer"
        helper.mkdir()
        installer_source = source / "installer"
        for name in (
            "setup.py",
            "installer_bundle.py",
            "installer_checks.py",
            "installer_journal.py",
            "installer_ui.py",
        ):
            shutil.copy2(installer_source / name, helper / name)
        (stage / ".build-info.json").write_text(
            json.dumps({"name": NAME, "format": 1}) + "\n", encoding="utf-8"
        )
        if destination.exists():
            shutil.rmtree(destination)
        shutil.move(str(stage), destination)
    print(f"Built npm candidate: {destination.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
