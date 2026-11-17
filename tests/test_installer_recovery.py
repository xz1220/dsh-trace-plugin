"""Release updates and recovery use isolated synthetic files and fake commands."""

import contextlib
import io
import json
import py_compile
import sys
import time
import unittest
from unittest.mock import patch

import test_setup as fixtures


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.SetupTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.payload = self.case.payload
        self.home = self.case.home
        self.system = self.case.system

    def installer(self, payload=None, action="setup", *flags):
        return self.case.installer(action, "--bundle", str(payload or self.payload), *flags)

    def install(self, payload=None):
        instance = self.installer(payload)
        with contextlib.redirect_stderr(io.StringIO()):
            result = instance.setup()
        return instance, result

    def newer(self):
        return fixtures.make_npm_payload(self.case.root / "new-release", "0.2.20")

    @staticmethod
    def cache(instance, version="0.2.19"):
        return instance.codex_home / "plugins/cache/rollout-local/codex-dsh-trace" / version

    def interrupt(self, instance, kind, error=KeyboardInterrupt):
        original = instance.write_managed

        def injected(path, data, expected=fixtures.setup.UNSET):
            matches = (
                (kind == "state" and path == instance.state_path)
                or (kind == "bundle" and path.name == "main.py" and "marketplace" in path.parts)
                or (kind == "cache" and path.name == "main.py" and "cache" in path.parts)
                or (kind == "receipt" and path.name == ".dsh-trace-bundle.json")
            )
            if matches:
                raise error("injected interruption")
            return original(path, data, expected=expected)

        with patch.object(instance, "write_managed", side_effect=injected):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(error):
                    instance.setup()

    def test_upgrade_keeps_old_bundle_cache_recordings_and_unrelated_configuration(self):
        old, _ = self.install()
        receipt = old.bundle.active_receipt()
        old_cache = fixtures.tree_snapshot(self.cache(old))
        recording = old.trace_root / "keep.jsonl"
        recording.write_text("synthetic evidence")
        unrelated = old.codex_home / "unrelated.toml"
        unrelated.write_text("keep = true")
        updated, result = self.install(self.newer())
        self.assertEqual(result["pluginVersion"], "0.2.20")
        self.assertEqual(fixtures.tree_snapshot(self.cache(old)), old_cache)
        self.assertTrue((old.bundle.source_path / receipt["activeBundle"]).exists())
        self.assertEqual(recording.read_text(), "synthetic evidence")
        self.assertEqual(unrelated.read_text(), "keep = true")
        self.assertFalse(updated.pending_path.exists())

    def test_verified_generated_bytecode_does_not_block_normal_update(self):
        instance, _ = self.install()
        source = self.cache(instance) / "server/store.py"
        target = source.parent / "__pycache__" / f"store.{sys.implementation.cache_tag}.pyc"
        py_compile.compile(str(source), cfile=str(target), doraise=True)
        report = self.installer(action="doctor").doctor()["installedContent"]
        self.assertEqual(report["extra"], [])
        self.assertEqual(len(report["generatedBytecode"]), 1)
        self.assertEqual(self.install(self.newer())[1]["pluginVersion"], "0.2.20")

    def test_edited_bytecode_is_preserved_as_unowned_content(self):
        instance, _ = self.install()
        source = self.cache(instance) / "server/store.py"
        target = source.parent / "__pycache__" / f"store.{sys.implementation.cache_tag}.pyc"
        bytecode = py_compile.compile(str(source), cfile=str(target), doraise=True)
        with open(bytecode, "ab") as stream:
            stream.write(b"user data")
        before = fixtures.tree_snapshot(self.home)
        with self.assertRaisesRegex(fixtures.setup.SetupError, "unowned files"):
            self.install(self.newer())
        self.assertEqual(fixtures.tree_snapshot(self.home), before)

    def test_downgrade_and_unknown_state_fields_are_rejected(self):
        self.install(self.newer())
        with self.assertRaisesRegex(fixtures.setup.SetupError, "Downgrades"):
            self.install()
        instance = self.installer()
        state = json.loads(instance.state_path.read_text())
        state["userField"] = "preserve"
        instance.state_path.write_text(json.dumps(state))
        before = fixtures.tree_snapshot(self.home)
        with self.assertRaisesRegex(fixtures.setup.SetupError, "unrecognized setup state"):
            self.install()
        self.assertEqual(fixtures.tree_snapshot(self.home), before)

    def test_unpublished_legacy_development_receipt_is_not_adopted(self):
        instance, _ = self.install()
        receipt = json.loads(instance.bundle.receipt_path.read_text())
        receipt["format"] = 1
        del receipt["payloadManifest"], receipt["templates"]
        instance.bundle.receipt_path.write_text(json.dumps(receipt))
        before = fixtures.tree_snapshot(self.home)
        with self.assertRaisesRegex(fixtures.setup.SetupError, "not the published 0.2.19"):
            self.install(self.newer())
        self.assertEqual(fixtures.tree_snapshot(self.home), before)

    def test_newer_doctor_reports_old_installation_without_calling_it_corrupt(self):
        self.install()
        report = self.installer(self.newer(), "doctor").doctor()
        self.assertEqual(report["status"], "configured-needs-native-check")
        self.assertEqual(report["bundledMarketplace"]["version"], "0.2.19")
        self.assertFalse(report["bundledMarketplace"]["currentCandidate"])
        self.assertEqual(report["candidateVersion"], "0.2.20")

    def test_missing_owned_cache_file_is_repaired_without_deleting_extra_files(self):
        instance, _ = self.install()
        cache = self.cache(instance)
        server = cache / "server/main.py"
        expected = server.read_bytes()
        server.unlink()
        extra = cache / "user-note.txt"
        extra.write_text("keep")
        self.assertEqual(
            self.installer(action="doctor").doctor()["installedContent"]["status"], "missing-files"
        )
        self.install()
        self.assertEqual(server.read_bytes(), expected)
        self.assertEqual(extra.read_text(), "keep")

    def test_missing_owned_source_file_can_be_repaired_from_same_package(self):
        instance, _ = self.install()
        receipt = instance.bundle.active_receipt()
        server = (
            instance.bundle.source_path
            / receipt["activeBundle"]
            / "plugins/codex-dsh-trace/server/main.py"
        )
        expected = server.read_bytes()
        server.unlink()
        self.install()
        self.assertEqual(server.read_bytes(), expected)

    def test_user_cache_edit_blocks_setup_uninstall_and_backend_probe(self):
        instance, _ = self.install()
        (self.cache(instance) / "server/main.py").write_text("# user change")
        before = fixtures.tree_snapshot(self.home)
        report = self.installer(action="doctor").doctor()
        self.assertEqual(report["status"], "needs-setup")
        self.assertEqual(report["installedContent"]["status"], "modified")
        self.assertEqual(report["backend"]["status"], "not-run")
        with self.assertRaisesRegex(fixtures.setup.SetupError, "edited"):
            self.install()
        with self.assertRaisesRegex(fixtures.setup.SetupError, "edited"):
            self.installer(action="uninstall").uninstall()
        self.assertEqual(fixtures.tree_snapshot(self.home), before)

    def test_extra_cache_files_block_version_update_and_uninstall(self):
        instance, _ = self.install()
        extra = self.cache(instance) / "user-data.txt"
        extra.write_text("retain")
        before = fixtures.tree_snapshot(self.home)
        with self.assertRaisesRegex(fixtures.setup.SetupError, "unowned files"):
            self.install(self.newer())
        with self.assertRaisesRegex(fixtures.setup.SetupError, "unowned"):
            self.installer(action="uninstall").uninstall()
        self.assertEqual(fixtures.tree_snapshot(self.home), before)

    def test_python_move_recovers_without_overwriting_old_bundle(self):
        first, second = self.case.root / "python-a", self.case.root / "python-b"
        for binary in (first, second):
            binary.write_text("#!/bin/sh\nexit 0\n")
            binary.chmod(0o700)
        with patch.object(sys, "executable", str(first)):
            instance, _ = self.install()
            receipt = instance.bundle.active_receipt()
        first.unlink()
        with patch.object(sys, "executable", str(second)):
            updated, _ = self.install()
            self.assertEqual(updated.bundle.verify()["pythonExecutable"], str(second))
        mcp = json.loads((self.cache(updated) / ".mcp.json").read_text())
        self.assertEqual(mcp["mcpServers"]["rollout-viewer"]["command"], str(second))
        self.assertTrue((instance.bundle.source_path / receipt["activeBundle"]).exists())

    def test_caught_failure_retains_recoverable_plugin_ownership(self):
        instance = self.installer()
        self.interrupt(instance, "state", fixtures.setup.SetupError)
        self.assertTrue(instance.pending_path.exists())
        recovered, _ = self.install()
        self.assertTrue(json.loads(recovered.state_path.read_text())["pluginOwned"])
        with contextlib.redirect_stderr(io.StringIO()):
            self.installer(action="uninstall").uninstall()
        self.assertIsNone(self.system.plugin)

    def test_retry_after_interrupt_at_bundle_cache_and_state_checkpoints(self):
        for kind in ("bundle", "cache", "state"):
            with self.subTest(kind=kind):
                # Separate cases model a new process reading the same durable record.
                previous = self.case
                self.case = fixtures.SetupTests()
                self.case.setUp()
                self.addCleanup(self.case.doCleanups)
                self.payload, self.home, self.system = (
                    self.case.payload,
                    self.case.home,
                    self.case.system,
                )
                instance = self.installer()
                self.interrupt(instance, kind)
                before = fixtures.tree_snapshot(self.home)
                report = self.installer(action="doctor").doctor()
                self.assertEqual(report["bundledMarketplace"]["status"], "pending-recovery")
                dry = self.installer(None, "setup", "--dry-run").setup()
                self.assertEqual(dry["status"], "dry-run")
                self.assertEqual(fixtures.tree_snapshot(self.home), before)
                recovered, result = self.install()
                self.assertEqual(result["status"], "configured")
                self.assertTrue(json.loads(recovered.state_path.read_text())["pluginOwned"])
                self.assertFalse(recovered.pending_path.exists())
                self.case = previous

    def test_failed_update_preserves_previous_cache_and_can_retry(self):
        instance, _ = self.install()
        before = fixtures.tree_snapshot(self.cache(instance))
        payload = self.newer()
        self.system.failure = "plugin add codex-dsh-trace"
        with self.assertRaisesRegex(fixtures.setup.SetupError, "Retry: npx"):
            self.install(payload)
        self.assertEqual(fixtures.tree_snapshot(self.cache(instance)), before)
        self.system.failure = None
        updated, result = self.install(payload)
        self.assertEqual(result["pluginVersion"], "0.2.20")
        self.assertFalse(updated.pending_path.exists())

    def test_retry_preserves_the_recorded_trace_root_and_no_persist_choice(self):
        self.install()
        target = self.case.root / "selected-recordings"
        interrupted = self.installer(None, "setup", "--trace-root", str(target), "--no-persist")
        self.interrupt(interrupted, "state")
        recovered, result = self.install()
        self.assertEqual(result["plan"]["traceRoot"], str(target))
        self.assertFalse(result["plan"]["persistentLoginSetup"])
        self.assertFalse(recovered.launch_path.exists())
        self.assertEqual(json.loads(recovered.state_path.read_text())["traceRoot"], str(target))

    def test_update_retry_after_catalog_receipt_publication_gap(self):
        instance, _ = self.install()
        old = fixtures.tree_snapshot(self.cache(instance))
        payload = self.newer()
        self.interrupt(self.installer(payload), "receipt")
        updated, result = self.install(payload)
        self.assertEqual(result["pluginVersion"], "0.2.20")
        self.assertEqual(fixtures.tree_snapshot(self.cache(instance)), old)
        self.assertFalse(updated.pending_path.exists())

    def test_concurrent_operation_is_stopped_before_writing(self):
        holder, _ = self.install()
        holder.acquire_operation_lock()
        self.addCleanup(holder.release_operation_lock)
        before = fixtures.tree_snapshot(self.home)
        with self.assertRaisesRegex(fixtures.setup.SetupError, "Another setup"):
            self.install()
        self.assertEqual(fixtures.tree_snapshot(self.home), before)

    def test_uninstall_confirmation_time_cache_edit_is_preserved(self):
        instance, _ = self.install()
        uninstall = self.installer(action="uninstall")
        file = self.cache(instance) / "server/main.py"
        with patch.object(
            uninstall, "confirm", side_effect=lambda _: file.write_text("# concurrent edit")
        ):
            with self.assertRaisesRegex(fixtures.setup.SetupError, "Installed files changed"):
                uninstall.uninstall()
        self.assertEqual(file.read_text(), "# concurrent edit")
        self.assertIsNotNone(self.system.plugin)

    def test_recovery_preserves_user_edits_and_rejects_unrelated_journal_paths(self):
        instance = self.installer()
        self.interrupt(instance, "state")
        instance.launch_path.write_text("user edit")
        before = fixtures.tree_snapshot(self.home)
        with self.assertRaisesRegex(fixtures.setup.SetupError, "user edit"):
            self.install()
        self.assertEqual(fixtures.tree_snapshot(self.home), before)
        pending = json.loads(instance.pending_path.read_text())
        pending["writes"].append(
            {"path": str(self.home / "unrelated.txt"), "before": None, "after": "0" * 64}
        )
        instance.pending_path.write_text(json.dumps(pending))
        with self.assertRaisesRegex(fixtures.setup.SetupError, "unrelated path"):
            self.install()

    def test_recovery_requires_original_package_and_preserves_foreign_environment(self):
        instance = self.installer()
        self.interrupt(instance, "state")
        with self.assertRaisesRegex(fixtures.setup.SetupError, "Finish the interrupted version"):
            self.install(self.newer())
        self.system.environment = "/foreign/recordings"
        before = fixtures.tree_snapshot(self.home)
        with self.assertRaisesRegex(fixtures.setup.SetupError, "environment changed"):
            self.install()
        self.assertEqual(fixtures.tree_snapshot(self.home), before)

    def test_uninstall_can_use_a_newer_helper_and_does_not_require_old_python(self):
        python = self.case.root / "python-old"
        python.write_text("#!/bin/sh\nexit 0\n")
        python.chmod(0o700)
        with patch.object(sys, "executable", str(python)):
            self.install()
        python.unlink()
        with contextlib.redirect_stderr(io.StringIO()):
            result = self.installer(self.newer(), "uninstall").uninstall()
        self.assertEqual(result["status"], "uninstalled")


class BackendProbeTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.SetupTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.cache = self.case.root / "probe-cache"
        (self.cache / "server").mkdir(parents=True)

    def run_probe(self, source, **budgets):
        file = self.cache / "server/main.py"
        file.write_text(source)
        return fixtures.setup.System().probe_backend(
            sys.executable,
            self.cache,
            {"server/main.py": fixtures.setup.digest(file.read_bytes())},
            **budgets,
        )

    def test_probe_isolated_environment_and_mcp_contract(self):
        source = """import json,os,sys
assert os.environ['CODEX_HOME'].startswith(os.environ['HOME'])
assert not os.listdir(os.environ['CODEX_ROLLOUT_TRACE_ROOT'])
for line in sys.stdin:
 r=json.loads(line)
 result={'serverInfo':{'version':'0.2.19'}} if r['id']==1 else {'tools':[{'name':'open_rollout_viewer'}]}
 print(json.dumps({'jsonrpc':'2.0','id':r['id'],'result':result}),flush=True)
"""
        self.assertEqual(self.run_probe(source)["status"], "verified")

    def test_timeout_and_output_limit_are_bounded(self):
        started = time.monotonic()
        self.assertEqual(
            self.run_probe("import time; time.sleep(30)", timeout=0.1)["status"], "timeout"
        )
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(
            self.run_probe(
                "import sys; sys.stdout.write('x'*10000); sys.stdout.flush()", limit=128
            )["status"],
            "output-limit",
        )

    def test_changed_code_is_not_executed(self):
        marker = self.case.root / "should-not-exist"
        file = self.cache / "server/main.py"
        file.write_text(f"from pathlib import Path; Path({str(marker)!r}).touch()")
        report = fixtures.setup.System().probe_backend(
            sys.executable, self.cache, {"server/main.py": "0" * 64}
        )
        self.assertEqual(report["status"], "unknown")
        self.assertFalse(marker.exists())
