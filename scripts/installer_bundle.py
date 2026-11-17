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

# Public 0.2.19 is the only format-1 release accepted as an update baseline.
RELEASE_0219_DIGEST = "f17fca3dcfbb1c9a8a43fae57652f287f813361f1a45af02709066dc2d7750eb"
RELEASE_0219_MANIFEST = {
    "files": {
        ".agents/plugins/marketplace.json": "d42cd968c9a2886277cfbdab838bd47922fee5209e9f5704f13e9593dd7c97cf",
        "plugins/codex-dsh-trace/.codex-plugin/plugin.json": "5f42bcbc1c339ba8127a62cbdb9ef9dec49815e635fae2b57eb881f83628e717",
        "plugins/codex-dsh-trace/.mcp.json": "eb16799d09129821705e40895d1fd221023a91d7408fe90a8d274617d8167477",
        "plugins/codex-dsh-trace/LICENSE": "f9008a36ee9b94c4813c63d8ff91e45eebabfeccc05f20d3fe3ad7f333a80b33",
        "plugins/codex-dsh-trace/README.md": "1846eea2ab0a7d4cca51137db52b3beb7c3c5d9197fc70741757221db8dc551e",
        "plugins/codex-dsh-trace/THIRD_PARTY_NOTICES.txt": "c5b806d4f1639d6189709dd44927d4116d8768abe4e3cf8ba2fba16eced2bc46",
        "plugins/codex-dsh-trace/assets/icon.png": "546d57ec1f1e118543fe0d0a213f68e8946cfc760478318552d1a38ee0c49743",
        "plugins/codex-dsh-trace/assets/icon.svg": "1838b9a931c427e48bd28ef4a27260c32154f71e8de2399a61c1a66d4d0e912d",
        "plugins/codex-dsh-trace/assets/logo-dark.png": "1e0d9dfa4aca65294b3818b12a77bd93576e83fab44f05dbfec0998494cbca64",
        "plugins/codex-dsh-trace/assets/logo-dark.svg": "83b2c2412d3f2136ceaf7411b1fb12689dc0c8f922e952782554e0a526e92906",
        "plugins/codex-dsh-trace/assets/logo.png": "8baa625615a41d12fc579b0fef30a4f251ba3033ab1b60ca21b8b6897861da46",
        "plugins/codex-dsh-trace/assets/viewer.html": "c4db62d1ee2cdea1aeec62df30946bc448bd865354d4407e55a2e1733e886c73",
        "plugins/codex-dsh-trace/server/_version.py": "6c9bef731c420fb39b3ed308997731d3c356b6ce0d5022054f0a84d6e782ce2a",
        "plugins/codex-dsh-trace/server/bridge-harness.html": "0cfbb6db136de317dc1df9f58a2b3b34b8a3a6b829e8c6ee051137048c7a88ae",
        "plugins/codex-dsh-trace/server/bundle_index.py": "a56e286f86c6e819cd300c6cea76360301c8a59740191d67411f7553b3a3932b",
        "plugins/codex-dsh-trace/server/catalog.py": "cbd62a9e9a78695f61807c5ea7226309b82ddd01d84557c67546a9a40e6848bc",
        "plugins/codex-dsh-trace/server/main.py": "2a50e818a123e1197fe0c8af0ce521e4862aa21b492f2e34567d89d304b071a6",
        "plugins/codex-dsh-trace/server/preview.py": "29f159ca059dd1c02244e797f0c6a92d1906fdbf91a3efc2f0651cbf89a3bc2e",
        "plugins/codex-dsh-trace/server/projection.py": "8de56eac46633c385963b0e1e7f3674cb7543b0c7631f1767357143bc81edbb3",
        "plugins/codex-dsh-trace/server/recorded_content.py": "b1ab7d824dcac1dfc46ad9490e05665fa67be10f1480327c0857e4e48e0fcd31",
        "plugins/codex-dsh-trace/server/recording.py": "9b7cc5c569c22ef5a365742c5b3131ac635f3005d43c9a5a8f863641e183fd7b",
        "plugins/codex-dsh-trace/server/snapshots.py": "8e2e78a31f0073f7a4738bc16c757ec1165a16969bf5ae63ad7b386d022fff55",
        "plugins/codex-dsh-trace/server/store.py": "42909b18b4658a5d301a4f5cde9e9cdf7f32170f7f11f1d07f2d0a49de0c338b",
        "plugins/codex-dsh-trace/server/thread_index.py": "dd49b072b8b2ab17f070e0eb19fb0f24a3ec7e3673a82dfa6b4615068cc579d1",
        "plugins/codex-dsh-trace/server/trajectory-locales.json": "24fe8ac4429997fdcaafdc7707b12d6dd4809fa04b695ab952b12d5e28c702c0",
    },
    "format": 1,
    "name": "dsh-trace-extension",
    "repository": "xz1220/dsh-trace-plugin",
    "version": "0.2.19",
}
RELEASE_0219_TEMPLATES = {
    ".agents/plugins/marketplace.json": '{\n  "name": "rollout-local",\n  "interface": {\n    "displayName": "Codex Trace"\n  },\n  "plugins": [\n    {\n      "name": "codex-dsh-trace",\n      "source": {\n        "source": "local",\n        "path": "./plugins/codex-dsh-trace"\n      },\n      "policy": {\n        "installation": "AVAILABLE",\n        "authentication": "ON_INSTALL"\n      },\n      "category": "Developer Tools"\n    }\n  ]\n}\n',
    "plugins/codex-dsh-trace/.mcp.json": '{\n  "mcpServers": {\n    "rollout-viewer": {\n      "command": "python3",\n      "args": ["./server/main.py"],\n      "cwd": ".",\n      "env_vars": ["CODEX_HOME", "CODEX_ROLLOUT_TRACE_ROOT"]\n    }\n  }\n}\n',
}


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
    if path.stat().st_size > 128 * 1024 * 1024:
        raise BundleError(f"Preserving oversized bundle file: {path}")
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
        self.manifest = manifest
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

    def _load_owned(self, allow_missing=False):
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
                | ({"payloadManifest", "templates"} if receipt.get("format") == 2 else set())
                or receipt.get("format") not in (1, 2)
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
            expected_active = f"bundles/{receipt['version']}-{receipt['packageDigest'][:16]}-{digest(receipt['pythonExecutable'].encode())[:8]}"
            if active != expected_active:
                raise BundleError(
                    "Receipt bundle path does not match its version, payload and Python identity."
                )
            if len(receipt["files"]) > 1000:
                raise BundleError("Marketplace receipt contains too many files.")
            manifest, templates = self._receipt_payload(receipt)
            expected_files = self._receipt_files(
                manifest, templates, active, receipt["pythonExecutable"]
            )
            if receipt["files"] != expected_files:
                raise BundleError("Receipt file ownership does not match its retained payload.")
            missing = []
            for name, expected in receipt["files"].items():
                installed_name(name)
                if name != CATALOG and not name.startswith(active + "/"):
                    raise BundleError(
                        "Receipt contains files outside the current development bundle."
                    )
                if not isinstance(expected, str) or not SHA.fullmatch(expected):
                    raise BundleError("Receipt contains an invalid file checksum.")
                data = read_bytes(self.source_path / name)
                if data is None and allow_missing:
                    missing.append(name)
                    continue
                if data is None or digest(data) != expected:
                    raise BundleError(
                        f"Managed marketplace file is missing or was edited: {name}. "
                        "Preserve your changes and review this path before retrying setup."
                    )
            self.missing_files = missing
            if missing:
                return receipt, receipt_raw
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

    def _receipt_payload(self, receipt):
        if receipt["format"] == 1:
            if receipt["version"] != "0.2.19" or receipt["packageDigest"] != RELEASE_0219_DIGEST:
                raise BundleError(
                    "This is not the published 0.2.19 installation. Preserve the historical "
                    "development source; use a clean Codex profile or review it manually."
                )
            manifest, templates = RELEASE_0219_MANIFEST, RELEASE_0219_TEMPLATES
        else:
            manifest, templates = receipt["payloadManifest"], receipt["templates"]
        if (
            not isinstance(manifest, dict)
            or manifest.get("format") != 1
            or manifest.get("name") != OWNER
            or manifest.get("repository") != REPOSITORY
            or manifest.get("version") != receipt["version"]
            or not isinstance(manifest.get("files"), dict)
            or not REQUIRED.issubset(manifest["files"])
            or len(manifest["files"]) > 1000
            or digest(encoded(manifest)) != receipt["packageDigest"]
            or not isinstance(templates, dict)
            or set(templates) != {CATALOG, PREFIX + ".mcp.json"}
        ):
            raise BundleError("Invalid retained payload identity; preserve the receipt for review.")
        for name, checksum in manifest["files"].items():
            runtime_name(name)
            if not isinstance(checksum, str) or not SHA.fullmatch(checksum):
                raise BundleError("Invalid retained payload checksum.")
        for name, raw in templates.items():
            if (
                not isinstance(raw, str)
                or len(raw) > 65536
                or digest(raw.encode()) != manifest["files"][name]
            ):
                raise BundleError("Invalid retained configuration template.")
        self._validate_catalog(templates[CATALOG].encode())
        return manifest, templates

    @staticmethod
    def _receipt_files(manifest, templates, active, python):
        catalog = json.loads(templates[CATALOG])
        catalog["plugins"][0]["source"]["path"] = f"./{active}/{PREFIX.rstrip('/')}"
        mcp = json.loads(templates[PREFIX + ".mcp.json"])
        servers = mcp.get("mcpServers", {})
        if (
            set(servers) != {"rollout-viewer"}
            or servers["rollout-viewer"].get("command") != "python3"
            or servers["rollout-viewer"].get("args") != ["./server/main.py"]
        ):
            raise BundleError("Invalid retained MCP template.")
        servers["rollout-viewer"]["command"] = python
        return {
            (name if name == CATALOG else active + "/" + name): digest(encoded(catalog))
            if name == CATALOG
            else digest(encoded(mcp))
            if name == PREFIX + ".mcp.json"
            else checksum
            for name, checksum in manifest["files"].items()
        }

    def active_receipt(self, allow_missing=False):
        return self._load_owned(allow_missing)[0]

    def cache_files(self, receipt=None):
        receipt = receipt or self.active_receipt()
        if receipt is None:
            return {}
        prefix = receipt["activeBundle"] + "/" + PREFIX
        return {
            name[len(prefix) :]: checksum
            for name, checksum in receipt["files"].items()
            if name.startswith(prefix)
        }

    def candidate_files(self):
        return {
            name[len(PREFIX) :]: self._patched_plugin_file(name, data)
            for name, data in self.payload.items()
            if name.startswith(PREFIX)
        }

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
            f"The same version has different package contents at {self.source_path}. "
            "Keep the installed release and select a newer stable package; do not replace a published version's contents. "
            "Historical development sources and user changes are preserved."
        )

    def plan(self, recovery_files=None):
        receipt, receipt_raw = self._load_owned(allow_missing=True)
        self.previous_receipt = receipt
        repairs = {}
        for name, data in (recovery_files or {}).items():
            if (
                not receipt
                or name not in self.missing_files
                or not name.startswith(receipt["activeBundle"] + "/" + PREFIX)
                or not isinstance(data, bytes)
                or digest(data) != receipt["files"].get(name)
            ):
                raise BundleError(
                    "Recovery bytes do not match a missing file owned by the old receipt."
                )
            repairs[name] = data
        if receipt:
            old = tuple(int(x) for x in receipt["version"].split("-")[0].split("."))
            new = tuple(int(x) for x in self.version.split("-")[0].split("."))
            if "-" in receipt["version"] or "-" in self.version or old < (0, 2, 19) or new < old:
                raise BundleError(
                    "Downgrades and historical development migrations are not supported. Keep the installed release or select a newer stable version."
                )
            if new == old and receipt["packageDigest"] != self.package_digest:
                raise BundleError(self._different_candidate_message())
            unresolved = sorted(set(self.missing_files) - set(repairs))
            if unresolved and receipt["packageDigest"] != self.package_digest:
                raise BundleError(
                    f"Automatic recovery requires original bytes from a complete verified old cache. Missing {receipt['version']} source files: "
                    + ", ".join(unresolved[:5])
                    + ". Preserve the installed backend, recordings and receipt. Restore only these absent paths "
                    "from an independently verified original archive or backup, then retry this current helper. "
                    + (
                        "The published 0.2.19 setup cannot repair this state."
                        if receipt["version"] == "0.2.19"
                        else "No original bytes will be guessed or downloaded automatically."
                    )
                )
        desired = {}
        for name, data in self.payload.items():
            if name != CATALOG:
                desired[self.bundle_relative + "/" + name] = self._patched_plugin_file(name, data)
        catalog = self._validate_catalog(self.payload[CATALOG])
        catalog["plugins"][0]["source"]["path"] = f"./{self.bundle_relative}/{PREFIX.rstrip('/')}"
        desired[CATALOG] = encoded(catalog)
        hashes = {name: digest(data) for name, data in desired.items()}
        desired_receipt = {
            "format": 2,
            "owner": OWNER,
            "repository": REPOSITORY,
            "version": self.version,
            "packageDigest": self.package_digest,
            "pythonExecutable": self.python_executable,
            "activeBundle": self.bundle_relative,
            "files": hashes,
            "payloadManifest": self.manifest,
            "templates": {
                name: self.payload[name].decode() for name in (CATALOG, PREFIX + ".mcp.json")
            },
        }
        desired[RECEIPT] = encoded(desired_receipt)
        # Retain only exact old bytes, outside the new receipt's active-file map.
        # They go through the caller's normal confirmation, CAS and durable journal.
        desired = {**repairs, **desired}
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
        self._receipt_before = receipt_raw
        self._desired_files = desired
        return {
            "source": str(self.source_path),
            "version": self.version,
            "changed": changed,
            "changes": (
                [
                    {
                        "action": "restore-missing-owned-source",
                        "path": str(self.source_path),
                        "files": sorted(repairs),
                    }
                ]
                if repairs
                else []
            )
            + [
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
        self._load_owned(allow_missing=True)
        if read_bytes(self.receipt_path) != self._receipt_before:
            raise BundleError("Marketplace receipt changed since inspection.")
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
        result = self.verify(require_current=True)
        if not result["valid"]:
            raise BundleError(result["reason"])
        return result

    def verify(self, require_current=False, check_runtime=True):
        try:
            receipt, _ = self._load_owned()
            if receipt is None:
                return {"valid": False, "status": "missing", "reason": "No managed npm source."}
            if require_current and not self._same_candidate(receipt):
                return {
                    "valid": False,
                    "status": "different-candidate",
                    "reason": self._different_candidate_message(),
                }
            python = Path(receipt["pythonExecutable"])
            runtime_available = python.is_file() and os.access(python, os.X_OK)
            if check_runtime and not runtime_available:
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
                "currentCandidate": self._same_candidate(receipt),
                "activeBundle": receipt["activeBundle"],
                "runtimeAvailable": runtime_available,
            }
        except (BundleError, OSError) as exc:
            return {"valid": False, "status": "missing-or-edited", "reason": str(exc)}

    def commit_source(self):
        """Paths to retain if Codex may already refer to this source on failure."""
        if self._desired_files is None:
            raise BundleError("Inspect the npm bundle plan before retaining its files.")
        return {self.source_path / name for name in self._desired_files}
