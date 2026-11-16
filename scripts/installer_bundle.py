"""Validate and persist the self-contained npm plugin without an npm-cache dependency."""

import hashlib
import json
import os
import re
import sys
from pathlib import Path, PurePosixPath

OWNER = "dsh-trace-extension"
REPOSITORY = "xz1220/dsh-trace-plugin"
MARKETPLACE = "rollout-local"
PLUGIN = "codex-dsh-trace"
CATALOG = ".agents/plugins/marketplace.json"
RECEIPT = ".dsh-trace-bundle.json"
PREFIX = f"plugins/{PLUGIN}/"
REQUIRED = {
    CATALOG,
    PREFIX + ".mcp.json",
    PREFIX + ".codex-plugin/plugin.json",
    PREFIX + "assets/viewer.html",
    PREFIX + "server/main.py",
    PREFIX + "server/store.py",
    PREFIX + "LICENSE",
    PREFIX + "THIRD_PARTY_NOTICES.txt",
}
SHA = re.compile(r"[0-9a-f]{64}\Z")
VERSION = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z.-]+))?\Z")


class BundleError(Exception):
    """An invalid payload or a destination that must be preserved."""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def safe_path(path):
    path = Path(path)
    for candidate in (path, *path.parents):
        if candidate.is_symlink():
            raise BundleError(f"Preserving symlinked bundle path: {candidate}")
    return path


def read_bytes(path):
    safe_path(path)
    if not path.exists():
        return None
    if not path.is_file():
        raise BundleError(f"Preserving non-file bundle path: {path}")
    return path.read_bytes()


def relative_name(value):
    if not isinstance(value, str) or not value or "\\" in value or "\0" in value:
        raise BundleError("Invalid path in bundle manifest.")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in value.split("/")):
        raise BundleError("Bundle paths must be relative and cannot traverse directories.")
    return value


def runtime_name(value):
    value = relative_name(value)
    if value != CATALOG and not value.startswith(PREFIX):
        raise BundleError(f"File is outside the plugin distribution allowlist: {value}")
    return value


def installed_name(value):
    value = relative_name(value)
    if value == CATALOG:
        return value
    parts = value.split("/")
    if (
        len(parts) < 5
        or parts[0] != "bundles"
        or not re.fullmatch(r"[0-9A-Za-z.-]+", parts[1])
        or not "/".join(parts[2:]).startswith(PREFIX)
    ):
        raise BundleError("Receipt contains a path outside the managed plugin bundles.")
    return value


def validate_version(value):
    if not isinstance(value, str) or not VERSION.fullmatch(value):
        raise BundleError("Bundle version is missing or invalid.")


class BundledMarketplace:
    def __init__(self, bundle_root, codex_home, python_executable=None):
        if Path(bundle_root).is_symlink():
            raise BundleError("Preserving a symlinked npm payload directory.")
        self.bundle_root = Path(bundle_root).resolve()
        self.source_path = Path(os.path.abspath(codex_home)) / OWNER / "marketplace"
        self.receipt_path = self.source_path / RECEIPT
        self.python_executable = str(Path(python_executable or sys.executable).resolve())
        self._snapshot = None
        self._desired_files = None
        self._read_payload()

    def _read_payload(self):
        manifest_file = self.bundle_root / "bundle-manifest.json"
        raw = read_bytes(manifest_file)
        if raw is None or len(raw) > 1024 * 1024:
            raise BundleError("Missing or oversized npm bundle manifest.")
        try:
            manifest = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise BundleError("Invalid npm bundle manifest JSON.") from exc
        if (
            not isinstance(manifest, dict)
            or manifest.get("format") != 1
            or manifest.get("name") != OWNER
            or manifest.get("repository") != REPOSITORY
            or not isinstance(manifest.get("files"), dict)
        ):
            raise BundleError("Unrecognized npm bundle identity.")
        self.version = manifest.get("version")
        validate_version(self.version)
        self.repository = manifest["repository"]
        files = manifest["files"]
        if not REQUIRED.issubset(files) or len(files) > 1000:
            raise BundleError("The npm bundle is missing required plugin files.")
        self.payload = {}
        total = 0
        for name, expected in sorted(files.items()):
            runtime_name(name)
            if not isinstance(expected, str) or not SHA.fullmatch(expected):
                raise BundleError("Invalid file checksum in npm bundle manifest.")
            data = read_bytes(self.bundle_root / name)
            if data is None or digest(data) != expected:
                raise BundleError(f"Bundled plugin file is missing or changed: {name}")
            total += len(data)
            if total > 128 * 1024 * 1024:
                raise BundleError("The npm plugin payload exceeds the supported size.")
            self.payload[name] = data
        self._validate_catalog(self.payload[CATALOG])
        try:
            plugin = json.loads(self.payload[PREFIX + ".codex-plugin/plugin.json"])
            if plugin.get("name") != PLUGIN or plugin.get("version") != self.version:
                raise BundleError("Plugin version does not match the npm bundle version.")
        except (ValueError, AttributeError) as exc:
            raise BundleError("Invalid bundled plugin metadata.") from exc
        self.package_digest = digest(encoded(manifest))
        python_digest = digest(self.python_executable.encode())[:8]
        self.token = f"{self.version}-{self.package_digest[:16]}-{python_digest}"
        self.bundle_relative = "bundles/" + self.token
        self.bundle_path = self.source_path / self.bundle_relative

    @staticmethod
    def _validate_catalog(raw):
        try:
            catalog = json.loads(raw)
            plugins = catalog.get("plugins")
            if (
                catalog.get("name") != MARKETPLACE
                or not isinstance(plugins, list)
                or len(plugins) != 1
                or plugins[0].get("name") != PLUGIN
                or plugins[0].get("source")
                != {"source": "local", "path": "./" + PREFIX.rstrip("/")}
            ):
                raise BundleError("The bundle does not contain the expected local marketplace.")
            return catalog
        except (ValueError, TypeError, AttributeError) as exc:
            raise BundleError("Invalid bundled marketplace catalog.") from exc

    def _load_owned(self):
        safe_path(self.source_path)
        receipt_raw = read_bytes(self.receipt_path)
        if receipt_raw is None:
            if self.source_path.exists():
                raise BundleError(
                    f"Preserving an unrecognized marketplace directory: {self.source_path}"
                )
            return None, None
        if len(receipt_raw) > 2 * 1024 * 1024:
            raise BundleError("Preserving an oversized marketplace receipt.")
        try:
            receipt = json.loads(receipt_raw)
            if (
                not isinstance(receipt, dict)
                or set(receipt)
                != {
                    "format",
                    "owner",
                    "repository",
                    "version",
                    "packageDigest",
                    "pythonExecutable",
                    "activeBundle",
                    "files",
                }
                or receipt.get("format") != 1
                or receipt.get("owner") != OWNER
                or receipt.get("repository") != REPOSITORY
                or not isinstance(receipt.get("files"), dict)
                or CATALOG not in receipt["files"]
                or not isinstance(receipt.get("packageDigest"), str)
                or not SHA.fullmatch(receipt["packageDigest"])
            ):
                raise BundleError("Preserving an unrecognized npm marketplace receipt.")
            validate_version(receipt.get("version"))
            active = relative_name(receipt.get("activeBundle"))
            if not re.fullmatch(r"bundles/[0-9A-Za-z.-]+", active):
                raise BundleError("Receipt has an invalid active bundle.")
            if not all(active + "/" + name in receipt["files"] for name in REQUIRED - {CATALOG}):
                raise BundleError("Receipt is missing active plugin files.")
            if (
                not isinstance(receipt.get("pythonExecutable"), str)
                or not Path(receipt["pythonExecutable"]).is_absolute()
            ):
                raise BundleError("Receipt has an invalid Python executable.")
            if len(receipt["files"]) > 1000:
                raise BundleError("Marketplace receipt contains too many files.")
            for name, expected in receipt["files"].items():
                installed_name(name)
                if name != CATALOG and not name.startswith(active + "/"):
                    raise BundleError(
                        "Receipt contains files outside the current development bundle."
                    )
                if not isinstance(expected, str) or not SHA.fullmatch(expected):
                    raise BundleError("Receipt contains an invalid file checksum.")
                data = read_bytes(self.source_path / name)
                if data is None or digest(data) != expected:
                    raise BundleError(f"Managed marketplace file is missing or was edited: {name}")
            catalog = json.loads(read_bytes(self.source_path / CATALOG))
            expected_path = f"./{active}/{PREFIX.rstrip('/')}"
            if (
                catalog.get("name") != MARKETPLACE
                or len(catalog.get("plugins", [])) != 1
                or catalog["plugins"][0].get("name") != PLUGIN
                or catalog["plugins"][0].get("source") != {"source": "local", "path": expected_path}
            ):
                raise BundleError("Managed marketplace catalog does not match its receipt.")
            plugin = json.loads(
                read_bytes(self.source_path / active / PREFIX / ".codex-plugin/plugin.json")
            )
            mcp = json.loads(read_bytes(self.source_path / active / PREFIX / ".mcp.json"))
            if plugin.get("name") != PLUGIN or plugin.get("version") != receipt["version"]:
                raise BundleError("Managed plugin version does not match its receipt.")
            if (
                mcp.get("mcpServers", {}).get("rollout-viewer", {}).get("command")
                != receipt["pythonExecutable"]
            ):
                raise BundleError("Managed Python executable does not match its receipt.")
        except (ValueError, TypeError, AttributeError, KeyError) as exc:
            raise BundleError("Preserving an invalid marketplace receipt.") from exc
        return receipt, receipt_raw

    def _patched_plugin_file(self, name, data):
        if name != PREFIX + ".mcp.json":
            return data
        try:
            value = json.loads(data)
            servers = value.get("mcpServers")
            if not isinstance(servers, dict) or set(servers) != {"rollout-viewer"}:
                raise BundleError("Unexpected bundled MCP server configuration.")
            server = servers["rollout-viewer"]
            if server.get("command") != "python3" or server.get("args") != ["./server/main.py"]:
                raise BundleError("Unexpected bundled Python launch configuration.")
            server["command"] = self.python_executable
            return encoded(value)
        except (ValueError, TypeError, AttributeError) as exc:
            raise BundleError("Invalid bundled MCP configuration.") from exc

    def _same_candidate(self, receipt):
        return (
            receipt["version"] == self.version
            and receipt["packageDigest"] == self.package_digest
            and receipt["pythonExecutable"] == self.python_executable
            and receipt["activeBundle"] == self.bundle_relative
        )

    def _different_candidate_message(self):
        return (
            f"A different development bundle is installed at {self.source_path}; "
            "rebuild the isolated development environment before setup. "
            "No recording data was changed."
        )

    def plan(self):
        receipt, receipt_raw = self._load_owned()
        if receipt and not self._same_candidate(receipt):
            raise BundleError(self._different_candidate_message())
        desired = {}
        for name, data in self.payload.items():
            if name != CATALOG:
                desired[self.bundle_relative + "/" + name] = self._patched_plugin_file(name, data)
        catalog = self._validate_catalog(self.payload[CATALOG])
        catalog["plugins"][0]["source"]["path"] = f"./{self.bundle_relative}/{PREFIX.rstrip('/')}"
        desired[CATALOG] = encoded(catalog)
        hashes = {name: digest(data) for name, data in desired.items()}
        desired_receipt = {
            "format": 1,
            "owner": OWNER,
            "repository": REPOSITORY,
            "version": self.version,
            "packageDigest": self.package_digest,
            "pythonExecutable": self.python_executable,
            "activeBundle": self.bundle_relative,
            "files": hashes,
        }
        desired[RECEIPT] = encoded(desired_receipt)
        snapshot = {}
        for name, data in desired.items():
            current = read_bytes(self.source_path / name)
            if current is not None and name not in (CATALOG, RECEIPT) and current != data:
                raise BundleError(f"Preserving unexpected existing bundle file: {name}")
            snapshot[name] = current
        if receipt_raw != snapshot[RECEIPT]:
            raise BundleError("Marketplace receipt changed during inspection.")
        changed = any(snapshot[name] != data for name, data in desired.items())
        self._snapshot = snapshot
        self._desired_files = desired
        return {
            "source": str(self.source_path),
            "version": self.version,
            "changed": changed,
            "changes": [
                {
                    "action": "persist-bundled-plugin",
                    "path": str(self.source_path),
                    "version": self.version,
                    "files": len(desired),
                }
            ]
            if changed
            else [],
        }

    def revalidate(self):
        if self._snapshot is None:
            raise BundleError("Inspect the npm bundle plan before applying it.")
        self._load_owned()
        for name, expected in self._snapshot.items():
            if read_bytes(self.source_path / name) != expected:
                raise BundleError(f"Bundle destination changed since inspection: {name}")

    def apply(self, write_managed, ensure_directory):
        self.revalidate()
        # Immutable plugin files first; publish the catalog and receipt last.
        names = sorted(n for n in self._desired_files if n not in (CATALOG, RECEIPT))
        names.extend([CATALOG, RECEIPT])
        for name in names:
            path = self.source_path / name
            ensure_directory(path.parent)
            write_managed(path, self._desired_files[name], expected=self._snapshot[name])
        result = self.verify()
        if not result["valid"]:
            raise BundleError(result["reason"])
        return result

    def verify(self):
        try:
            receipt, _ = self._load_owned()
            if receipt is None:
                return {"valid": False, "status": "missing", "reason": "No managed npm source."}
            if not self._same_candidate(receipt):
                return {
                    "valid": False,
                    "status": "different-development-bundle",
                    "reason": self._different_candidate_message(),
                }
            python = Path(receipt["pythonExecutable"])
            if not python.is_file() or not os.access(python, os.X_OK):
                return {
                    "valid": False,
                    "status": "missing-python",
                    "reason": "The Python executable pinned by the installed plugin is unavailable.",
                }
            return {
                "valid": True,
                "status": "verified",
                "version": receipt["version"],
                "source": str(self.source_path),
                "pythonExecutable": receipt["pythonExecutable"],
            }
        except (BundleError, OSError) as exc:
            return {"valid": False, "status": "missing-or-edited", "reason": str(exc)}

    def commit_source(self):
        """Paths to retain if Codex may already refer to this source on failure."""
        if self._desired_files is None:
            raise BundleError("Inspect the npm bundle plan before retaining its files.")
        return {self.source_path / name for name in self._desired_files}
