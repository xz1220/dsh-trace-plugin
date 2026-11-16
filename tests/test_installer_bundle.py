"""Verify npm payload persistence and ownership in isolated temporary homes."""

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "installer_bundle", Path(__file__).resolve().parents[1] / "scripts/installer_bundle.py"
)
bundle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bundle)


class Transaction:
    def __init__(self):
        self.writes = []
        self.previous = []

    def ensure(self, directory):
        directory.mkdir(parents=True, exist_ok=True)

    def write(self, path, data, expected):
        before = path.read_bytes() if path.exists() else None
        if before != expected:
            raise RuntimeError("concurrent change")
        if before == data:
            return
        self.previous.append((path, before))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self.writes.append(path)

    def rollback(self):
        for path, previous in reversed(self.previous):
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(previous)


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="trace-npm-bundle-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.home = self.root / "home"
        self.payload = self.create_payload(self.root / "npm-cache")

    def create_payload(self, root, version="0.2.19", extra=b""):
        root.mkdir(parents=True)
        catalog = {
            "name": "rollout-local",
            "plugins": [
                {
                    "name": "codex-dsh-trace",
                    "source": {"source": "local", "path": "./plugins/codex-dsh-trace"},
                }
            ],
        }
        files = {name: b"test fixture\n" for name in bundle.REQUIRED}
        files[bundle.CATALOG] = bundle.encoded(catalog)
        files[bundle.PREFIX + ".codex-plugin/plugin.json"] = bundle.encoded(
            {"name": "codex-dsh-trace", "version": version}
        )
        files[bundle.PREFIX + ".mcp.json"] = bundle.encoded(
            {
                "mcpServers": {
                    "rollout-viewer": {
                        "command": "python3",
                        "args": ["./server/main.py"],
                        "cwd": ".",
                    }
                }
            }
        )
        files[bundle.PREFIX + "assets/viewer.html"] = b"<!doctype html>actual bundled UI" + extra
        for name, data in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        manifest = {
            "format": 1,
            "name": bundle.OWNER,
            "version": version,
            "repository": bundle.REPOSITORY,
            "files": {name: bundle.digest(data) for name, data in files.items()},
        }
        (root / "bundle-manifest.json").write_bytes(bundle.encoded(manifest))
        return root

    def manager(self, payload=None, python=None):
        return bundle.BundledMarketplace(
            payload or self.payload, self.home, python or sys.executable
        )

    def install(self, manager=None):
        manager = manager or self.manager()
        manager.plan()
        transaction = Transaction()
        manager.apply(transaction.write, transaction.ensure)
        return manager, transaction

    def change_manifest(self, update):
        path = self.payload / "bundle-manifest.json"
        manifest = json.loads(path.read_bytes())
        update(manifest)
        path.write_bytes(bundle.encoded(manifest))

    def test_plan_does_not_create_persistent_directories(self):
        manager = self.manager()
        plan = manager.plan()
        self.assertTrue(plan["changed"])
        self.assertFalse(self.home.exists())
        self.assertIn("marketplace", str(manager.source_path))
        self.assertNotIn("npm-cache", str(manager.source_path))

    def test_install_pins_python_and_survives_npm_cache_removal(self):
        manager, _ = self.install()
        catalog = json.loads((manager.source_path / bundle.CATALOG).read_bytes())
        source = catalog["plugins"][0]["source"]["path"]
        installed_plugin = manager.source_path / source
        installed_mcp = json.loads((installed_plugin / ".mcp.json").read_bytes())
        self.assertEqual(
            installed_mcp["mcpServers"]["rollout-viewer"]["command"],
            str(Path(sys.executable).resolve()),
        )
        original = json.loads((self.payload / bundle.PREFIX / ".mcp.json").read_bytes())
        self.assertEqual(original["mcpServers"]["rollout-viewer"]["command"], "python3")
        shutil.rmtree(self.payload)
        self.assertTrue(manager.verify()["valid"])
        self.assertTrue((installed_plugin / "assets/viewer.html").is_file())

    def test_repeat_from_a_different_npm_cache_is_unchanged(self):
        manager, _ = self.install()
        second = self.create_payload(self.root / "other-cache")
        repeated = self.manager(second)
        before = manager.receipt_path.read_bytes()
        self.assertFalse(repeated.plan()["changed"])
        transaction = Transaction()
        repeated.apply(transaction.write, transaction.ensure)
        self.assertEqual(transaction.writes, [])
        self.assertEqual(manager.receipt_path.read_bytes(), before)

    def test_manifest_digest_mismatch_is_rejected_without_writes(self):
        (self.payload / bundle.PREFIX / "assets/viewer.html").write_bytes(b"changed")
        with self.assertRaisesRegex(bundle.BundleError, "missing or changed"):
            self.manager()
        self.assertFalse(self.home.exists())

    def test_manifest_traversal_and_foreign_paths_are_rejected(self):
        for name in ["../escape", "/absolute", "plugins/../escape", "private/token.txt"]:
            with self.subTest(name=name):
                path = self.payload / "bundle-manifest.json"
                original = path.read_bytes()
                self.change_manifest(lambda m: m["files"].update({name: "a" * 64}))
                with self.assertRaises(bundle.BundleError):
                    self.manager()
                path.write_bytes(original)
        self.assertFalse(self.home.exists())

    def test_symlinked_input_file_is_rejected_even_if_content_matches(self):
        target = self.payload / bundle.PREFIX / "assets/viewer.html"
        outside = self.root / "outside.html"
        outside.write_bytes(target.read_bytes())
        target.unlink()
        target.symlink_to(outside)
        with self.assertRaisesRegex(bundle.BundleError, "symlinked"):
            self.manager()

    def test_symlinked_payload_root_is_rejected(self):
        link = self.root / "payload-link"
        link.symlink_to(self.payload, target_is_directory=True)
        with self.assertRaisesRegex(bundle.BundleError, "symlinked"):
            self.manager(link)

    def test_verify_reports_a_removed_pinned_python(self):
        python = self.root / "verified-python"
        python.write_text("#!/bin/sh\nexit 0\n")
        python.chmod(0o700)
        manager, _ = self.install(self.manager(python=str(python)))
        python.unlink()
        result = manager.verify()
        self.assertFalse(result["valid"])
        self.assertEqual(result["status"], "missing-python")

    def test_missing_required_runtime_file_is_rejected(self):
        self.change_manifest(lambda m: m["files"].pop(bundle.PREFIX + "server/main.py"))
        with self.assertRaisesRegex(bundle.BundleError, "missing required"):
            self.manager()

    def test_plugin_and_package_versions_must_match(self):
        self.change_manifest(lambda m: m.update(version="0.3.0"))
        with self.assertRaisesRegex(bundle.BundleError, "does not match"):
            self.manager()

    def test_foreign_destination_is_not_adopted(self):
        manager = self.manager()
        manager.source_path.mkdir(parents=True)
        note = manager.source_path / "notes.txt"
        note.write_text("user content")
        with self.assertRaisesRegex(bundle.BundleError, "unrecognized marketplace"):
            manager.plan()
        self.assertEqual(note.read_text(), "user content")

    def test_edited_installed_file_is_preserved(self):
        manager, _ = self.install()
        target = manager.bundle_path / bundle.PREFIX / "assets/viewer.html"
        target.write_text("user modification")
        self.assertFalse(manager.verify()["valid"])
        with self.assertRaisesRegex(bundle.BundleError, "missing or was edited"):
            self.manager().plan()
        self.assertEqual(target.read_text(), "user modification")

    def test_edited_receipt_identity_is_not_trusted(self):
        manager, _ = self.install()
        data = json.loads(manager.receipt_path.read_bytes())
        data["owner"] = "someone-else"
        manager.receipt_path.write_bytes(bundle.encoded(data))
        self.assertFalse(manager.verify()["valid"])
        with self.assertRaisesRegex(bundle.BundleError, "unrecognized"):
            manager.plan()

    def test_user_added_receipt_fields_are_preserved(self):
        manager, _ = self.install()
        data = json.loads(manager.receipt_path.read_bytes())
        data["user-note"] = "keep this edit"
        original = bundle.encoded(data)
        manager.receipt_path.write_bytes(original)
        with self.assertRaisesRegex(bundle.BundleError, "unrecognized"):
            manager.plan()
        self.assertEqual(manager.receipt_path.read_bytes(), original)

    def test_receipt_cannot_claim_an_unrelated_file(self):
        manager, _ = self.install()
        data = json.loads(manager.receipt_path.read_bytes())
        data["files"]["../user-config"] = "a" * 64
        manager.receipt_path.write_bytes(bundle.encoded(data))
        self.assertFalse(manager.verify()["valid"])

    def test_edit_between_plan_and_apply_is_not_overwritten(self):
        manager, _ = self.install()
        manager.plan()
        catalog = manager.source_path / bundle.CATALOG
        catalog.write_text("a concurrent edit")
        with self.assertRaises(bundle.BundleError):
            manager.apply(Transaction().write, Transaction().ensure)
        self.assertEqual(catalog.read_text(), "a concurrent edit")

    def test_different_development_bundle_requires_rebuilding_the_environment(self):
        original, _ = self.install()
        before = {p: p.read_bytes() for p in original.source_path.rglob("*") if p.is_file()}
        candidates = [
            self.create_payload(self.root / "other-version", "0.3.0"),
            self.create_payload(self.root / "other-content", extra=b"changed candidate"),
        ]
        for payload in candidates:
            candidate = self.manager(payload)
            with self.assertRaisesRegex(bundle.BundleError, "different development bundle"):
                candidate.plan()
            self.assertEqual(candidate.verify()["status"], "different-development-bundle")
            self.assertEqual({p: p.read_bytes() for p in before}, before)

    def test_different_python_pin_is_a_different_development_candidate(self):
        self.install()
        python = self.root / "other-python"
        python.write_text("#!/bin/sh\nexit 0\n")
        python.chmod(0o700)
        candidate = self.manager(python=str(python))
        with self.assertRaisesRegex(bundle.BundleError, "rebuild the isolated"):
            candidate.plan()

    def test_unlisted_cache_files_are_not_copied(self):
        (self.payload / "private-recording.json").write_text("not distributed")
        manager, _ = self.install()
        self.assertFalse((manager.source_path / "private-recording.json").exists())

    def test_commit_source_excludes_unrelated_user_files(self):
        manager, _ = self.install()
        extra = manager.source_path / "user-note.txt"
        extra.write_text("keep")
        paths = manager.commit_source()
        self.assertIn(manager.receipt_path, paths)
        self.assertIn(manager.source_path / bundle.CATALOG, paths)
        self.assertNotIn(extra, paths)

    def test_verification_preserves_extra_user_files_and_recordings(self):
        manager, _ = self.install()
        extra = manager.source_path / "user-note.txt"
        extra.write_text("keep")
        recordings = self.home / "rollout-traces" / "recording.json"
        recordings.parent.mkdir()
        recordings.write_text("keep recording")
        self.assertTrue(manager.verify()["valid"])
        self.assertEqual(extra.read_text(), "keep")
        self.assertEqual(recordings.read_text(), "keep recording")

    def test_partial_copy_uses_the_callers_rollback_journal(self):
        manager = self.manager()
        manager.plan()
        transaction = Transaction()

        def fail_after_one(path, data, expected):
            if transaction.writes:
                raise RuntimeError("simulated write failure")
            transaction.write(path, data, expected)

        with self.assertRaisesRegex(RuntimeError, "simulated"):
            manager.apply(fail_after_one, transaction.ensure)
        transaction.rollback()
        self.assertFalse(any(p.is_file() for p in self.home.rglob("*")))


if __name__ == "__main__":
    unittest.main()
