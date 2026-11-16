"""Installer checks use fake commands and temporary homes, never real settings."""

import contextlib
import importlib.util
import io
import json
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "trace_setup", Path(__file__).resolve().parents[1] / "scripts/setup.py"
)
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


class FakeSystem:
    def __init__(self):
        self.calls = []
        self.environments = []
        self.search_paths = []
        self.marketplace = None
        self.plugin = None
        self.environment = None
        self.failure = None
        self.on_failure = None

    def which(self, name, path=None):
        self.search_paths.append((name, path))
        return {"codex": "/tools/codex", "launchctl": "/bin/launchctl"}.get(name)

    def run(self, command, env=None):
        self.calls.append(command)
        self.environments.append((command, dict(env or {})))
        words = command[1:]
        if self.failure and self.failure in " ".join(command):
            if self.on_failure:
                self.on_failure()
            return subprocess.CompletedProcess(command, 1, "", "simulated command failure")
        data = {}
        if words == ["--version"]:
            return subprocess.CompletedProcess(command, 0, "codex-cli 0.163.0\n", "")
        if words == ["plugin", "add", "--help"]:
            return subprocess.CompletedProcess(command, 0, "plugin add help", "")
        if words == ["plugin", "marketplace", "list", "--json"]:
            data = {"marketplaces": [self.marketplace] if self.marketplace else []}
        elif words == ["plugin", "list", "--marketplace", "rollout-local", "--json"]:
            data = {"installed": [self.plugin] if self.plugin else [], "available": []}
        elif words[:3] == ["plugin", "marketplace", "add"]:
            self.marketplace = {
                "name": "rollout-local",
                "marketplaceSource": {"sourceType": "git", "source": words[3]},
            }
        elif words[:2] == ["plugin", "add"]:
            self.plugin = {
                "pluginId": setup.PLUGIN,
                "installed": True,
                "enabled": True,
                "version": "0.2.19",
            }
        elif words[:2] == ["plugin", "remove"]:
            self.plugin = None
        elif words == ["getenv", setup.ENV_KEY]:
            return subprocess.CompletedProcess(
                command, 0 if self.environment is not None else 1, self.environment or "", ""
            )
        elif words[:2] == ["setenv", setup.ENV_KEY]:
            self.environment = words[2]
        elif words == ["unsetenv", setup.ENV_KEY]:
            self.environment = None
        elif command[:2] == ["git", "-C"]:
            return subprocess.CompletedProcess(
                command, 0, "https://github.com/xz1220/dsh-trace-plugin.git\n", ""
            )
        else:
            raise AssertionError(f"Unexpected command: {command}")
        return subprocess.CompletedProcess(command, 0, json.dumps(data), "")


def tree_snapshot(directory):
    return {
        str(path.relative_to(directory)): (path.read_bytes(), path.stat().st_mode & 0o777)
        for path in directory.rglob("*")
        if path.is_file()
    }


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="trace-installer-test-")
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name).resolve()
        self.system = FakeSystem()

    def installer(self, *arguments, platform="darwin"):
        return setup.Installer(
            setup.parser().parse_args([*arguments, "--yes"]),
            system=self.system,
            platform=platform,
            home=self.home,
            environ={},
        )

    def run_setup(self, *arguments):
        installer = self.installer(*arguments)
        with contextlib.redirect_stderr(io.StringIO()):
            result = installer.setup()
        return installer, result

    def test_tilde_arguments_use_the_selected_home(self):
        installer = self.installer("--codex-home", "~/custom-codex", "--trace-root", "~/traces")
        self.assertEqual(installer.codex_home, self.home / "custom-codex")
        self.assertEqual(installer.trace_root, self.home / "traces")
        self.assertEqual(installer.local_source("~/checkout"), self.home / "checkout")

    def test_uninstall_does_not_remove_a_plugin_from_a_replaced_marketplace(self):
        installer, _ = self.run_setup()
        self.system.marketplace["marketplaceSource"]["source"] = "unrelated/plugin"
        before = tree_snapshot(self.home)
        environment = self.system.environment
        with self.assertRaisesRegex(setup.SetupError, "different or unknown source"):
            self.installer("uninstall").uninstall()
        self.assertEqual(tree_snapshot(self.home), before)
        self.assertEqual(self.system.environment, environment)
        self.assertIsNotNone(self.system.plugin)

    def test_uninstall_checks_plugin_source_again_after_confirmation(self):
        self.run_setup()
        before = tree_snapshot(self.home)

        def replace_source(_installer, _plan):
            self.system.marketplace["marketplaceSource"]["source"] = "unrelated/plugin"

        with patch.object(setup.Installer, "confirm", replace_source):
            with self.assertRaisesRegex(setup.SetupError, "different or unknown source"):
                self.installer("uninstall").uninstall()
        self.assertEqual(tree_snapshot(self.home), before)
        self.assertIsNotNone(self.system.plugin)

    def test_success_installs_and_configures_only_owned_files(self):
        installer, result = self.run_setup("--ref", "release-commit")
        self.assertEqual(result["status"], "configured")
        self.assertFalse(result["nativeVerified"])
        self.assertEqual(self.system.environment, str(installer.trace_root))
        self.assertTrue(installer.state_path.is_file())
        self.assertEqual(installer.state_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(installer.trace_root.stat().st_mode & 0o777, 0o700)
        plist = plistlib.loads(installer.launch_path.read_bytes())
        self.assertEqual(
            plist["ProgramArguments"],
            ["/bin/launchctl", "setenv", setup.ENV_KEY, str(installer.trace_root)],
        )
        self.assertTrue(plist["RunAtLoad"])
        self.assertTrue(installer.state["owner"] if installer.state else True)
        self.assertIn(
            [
                "/tools/codex",
                "plugin",
                "marketplace",
                "add",
                setup.DEFAULT_SOURCE,
                "--ref",
                "release-commit",
                "--json",
            ],
            self.system.calls,
        )

    def test_repeat_setup_is_unchanged_and_does_not_rewrite_or_backup(self):
        installer, _ = self.run_setup()
        original = tree_snapshot(self.home)
        stat = installer.state_path.stat().st_mtime_ns
        calls = len(self.system.calls)
        _, result = self.run_setup()
        self.assertEqual(result["status"], "unchanged")
        self.assertEqual(tree_snapshot(self.home), original)
        self.assertEqual(installer.state_path.stat().st_mtime_ns, stat)
        self.assertFalse((installer.state_path.parent / "backups").exists())
        self.assertFalse(
            any(
                c[1:3] == ["plugin", "add"] and "--help" not in c for c in self.system.calls[calls:]
            )
        )

    def test_dry_run_leaves_home_and_environment_untouched(self):
        installer, result = self.run_setup("--dry-run")
        self.assertEqual(result["status"], "dry-run")
        self.assertEqual(list(self.home.iterdir()), [])
        self.assertIsNone(self.system.environment)
        self.assertFalse(installer.state_path.exists())

    def test_custom_codex_home_is_passed_to_every_cli_subprocess(self):
        custom = self.home / "separate codex config"
        installer, result = self.run_setup("--codex-home", str(custom))
        self.assertEqual(result["status"], "configured")
        self.assertEqual(installer.state_path, custom / setup.OWNER / "setup.json")
        codex_calls = [
            env for command, env in self.system.environments if command[0] == "/tools/codex"
        ]
        self.assertTrue(codex_calls)
        self.assertTrue(all(env["CODEX_HOME"] == str(custom) for env in codex_calls))
        self.assertTrue(all(env["HOME"] == str(self.home) for env in codex_calls))
        self.assertFalse((self.home / ".codex").exists())

    def test_injected_environment_is_used_for_discovery_and_child_commands(self):
        environment = {
            "PATH": "/isolated/tools",
            "CODEX_HOME": str(self.home / "injected-config"),
            "EXTRA": "kept",
        }
        installer = setup.Installer(
            setup.parser().parse_args(["--dry-run", "--yes"]),
            system=self.system,
            platform="darwin",
            home=self.home,
            environ=environment,
        )
        with contextlib.redirect_stderr(io.StringIO()):
            installer.setup()
        self.assertIn(("codex", "/isolated/tools"), self.system.search_paths)
        self.assertTrue(all(env["EXTRA"] == "kept" for _, env in self.system.environments))
        self.assertTrue(
            all(
                env["CODEX_HOME"] == str(installer.codex_home)
                for _, env in self.system.environments
            )
        )
        self.assertNotIn("HOME", environment)

    def test_foreign_marketplace_is_not_overwritten_even_with_yes(self):
        self.system.marketplace = {
            "name": "rollout-local",
            "marketplaceSource": {"sourceType": "git", "source": "other/project"},
        }
        with self.assertRaisesRegex(setup.SetupError, "different or unknown source"):
            self.run_setup()
        self.assertEqual(list(self.home.iterdir()), [])
        self.assertEqual(self.system.marketplace["marketplaceSource"]["source"], "other/project")

    def test_same_project_local_marketplace_is_reused(self):
        local = self.home / "source"
        (local / ".agents/plugins").mkdir(parents=True)
        (local / ".agents/plugins/marketplace.json").write_text(
            json.dumps(
                {
                    "name": "rollout-local",
                    "plugins": [{"name": "codex-dsh-trace"}],
                }
            )
        )
        self.system.marketplace = {
            "name": "rollout-local",
            "root": str(local),
            "marketplaceSource": {"sourceType": "local", "source": str(local)},
        }
        self.run_setup()
        self.assertFalse(any(c[1:4] == ["plugin", "marketplace", "add"] for c in self.system.calls))

    def test_foreign_login_environment_is_preserved(self):
        self.system.environment = str(self.home / "someone-elses-recordings")
        with self.assertRaisesRegex(setup.SetupError, "already points elsewhere"):
            self.run_setup()
        self.assertEqual(list(self.home.iterdir()), [])

    def test_distinct_checkouts_with_same_project_remote_are_reused(self):
        original = self.home / "original"
        checkout = self.home / "worktree"
        for source in [original, checkout]:
            (source / ".agents/plugins").mkdir(parents=True)
            (source / ".agents/plugins/marketplace.json").write_text(
                json.dumps({"name": "rollout-local", "plugins": [{"name": "codex-dsh-trace"}]})
            )
        self.system.marketplace = {
            "name": "rollout-local",
            "root": str(original),
            "marketplaceSource": {"sourceType": "local", "source": str(original)},
        }
        self.run_setup("--source", str(checkout))
        self.assertFalse(any(c[1:4] == ["plugin", "marketplace", "add"] for c in self.system.calls))

    def test_foreign_launch_agent_is_preserved(self):
        installer = self.installer()
        installer.launch_path.parent.mkdir(parents=True)
        installer.launch_path.write_bytes(b"user launch configuration")
        before = tree_snapshot(self.home)
        with self.assertRaisesRegex(setup.SetupError, "not owned"):
            self.run_setup()
        self.assertEqual(tree_snapshot(self.home), before)

    def test_edited_owned_agent_blocks_setup_and_uninstall_without_deleting_it(self):
        installer, _ = self.run_setup()
        installer.launch_path.write_bytes(installer.launch_path.read_bytes() + b"\nuser edit\n")
        before = tree_snapshot(self.home)
        with self.assertRaisesRegex(setup.SetupError, "was edited"):
            self.run_setup()
        with self.assertRaisesRegex(setup.SetupError, "was edited"):
            self.installer("uninstall").uninstall()
        self.assertEqual(tree_snapshot(self.home), before)
        self.assertIsNotNone(self.system.plugin)

    def test_failure_rolls_back_recording_changes_and_reports_cli_partial_state(self):
        self.system.failure = "plugin add codex-dsh-trace"
        with self.assertRaisesRegex(setup.SetupError, "Some Codex CLI commands completed"):
            self.run_setup()
        self.assertIsNone(self.system.environment)
        self.assertFalse(self.installer().launch_path.exists())
        self.assertFalse(self.installer().state_path.exists())
        self.assertIsNotNone(self.system.marketplace)
        self.system.failure = None
        _, result = self.run_setup()
        self.assertEqual(result["status"], "configured")

    def test_rollback_preserves_an_external_file_edit(self):
        installer = self.installer()
        self.system.failure = "plugin add codex-dsh-trace"
        self.system.on_failure = lambda: installer.launch_path.write_bytes(b"concurrent edit")
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(setup.SetupError):
                installer.setup()
        self.assertEqual(installer.launch_path.read_bytes(), b"concurrent edit")
        self.assertTrue(any("Concurrent edit" in warning for warning in installer.warnings))

    def test_doctor_is_read_only_and_old_recordings_are_not_native_verification(self):
        installer, _ = self.run_setup()
        bundle = installer.trace_root / "sample"
        bundle.mkdir()
        (bundle / "manifest.json").write_text('{"schema_version": 2}')
        (bundle / "trace.jsonl").write_text("{}\n")
        before = tree_snapshot(self.home)
        result = self.installer("doctor").doctor()
        self.assertEqual(result["compatibleRecordingBundles"], 1)
        self.assertFalse(result["nativeVerified"])
        self.assertEqual(result["status"], "configured-needs-native-check")
        self.assertEqual(tree_snapshot(self.home), before)

    def test_uninstall_preserves_recordings_user_config_and_marketplace(self):
        installer, _ = self.run_setup()
        recording = installer.trace_root / "precious.txt"
        recording.write_text("keep recording")
        config = installer.codex_home / "config.toml"
        config.write_text("# unrelated user settings\n")
        with contextlib.redirect_stderr(io.StringIO()):
            result = self.installer("uninstall").uninstall()
        self.assertEqual(result["status"], "uninstalled")
        self.assertFalse(result["recordingsDeleted"])
        self.assertEqual(recording.read_text(), "keep recording")
        self.assertEqual(config.read_text(), "# unrelated user settings\n")
        self.assertFalse(installer.launch_path.exists())
        self.assertFalse(installer.state_path.exists())
        self.assertIsNone(self.system.environment)
        self.assertIsNone(self.system.plugin)
        self.assertIsNotNone(self.system.marketplace)

    def test_existing_plugin_and_matching_environment_are_not_adopted(self):
        self.system.marketplace = {
            "name": "rollout-local",
            "marketplaceSource": {"sourceType": "git", "source": setup.DEFAULT_SOURCE},
        }
        self.system.plugin = {"pluginId": setup.PLUGIN, "installed": True, "enabled": True}
        self.system.environment = str(self.installer().trace_root)
        installer, _ = self.run_setup()
        state = json.loads(installer.state_path.read_text())
        self.assertFalse(state["pluginOwned"])
        self.assertFalse(state["environmentOwned"])
        with contextlib.redirect_stderr(io.StringIO()):
            self.installer("uninstall").uninstall()
        self.assertIsNotNone(self.system.plugin)
        self.assertEqual(self.system.environment, str(installer.trace_root))

    def test_no_persist_has_no_login_agent(self):
        installer, result = self.run_setup("--no-persist")
        self.assertEqual(result["status"], "configured")
        self.assertFalse(installer.launch_path.exists())
        self.assertIsNone(json.loads(installer.state_path.read_text())["launchAgent"])

    def test_uninstall_preserves_later_environment_change(self):
        installer, _ = self.run_setup()
        self.system.environment = "/user-changed-recording-root"
        with contextlib.redirect_stderr(io.StringIO()):
            result = self.installer("uninstall").uninstall()
        self.assertEqual(
            result["warnings"], ["Recording environment changed after setup and will be preserved."]
        )
        self.assertEqual(self.system.environment, "/user-changed-recording-root")
        self.assertTrue(installer.trace_root.exists())

    def test_symlinked_state_directory_is_rejected(self):
        installer = self.installer()
        target = self.home / "other"
        target.mkdir()
        installer.state_path.parent.parent.mkdir()
        installer.state_path.parent.symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(setup.SetupError, "symlink"):
            self.run_setup()
        self.assertEqual(list(target.iterdir()), [])

    def test_unsupported_platform_and_missing_codex_make_no_changes(self):
        with self.assertRaisesRegex(setup.SetupError, "macOS"):
            self.installer(platform="linux").setup()
        with patch.object(self.system, "which", return_value=None):
            with self.assertRaisesRegex(setup.SetupError, "Codex CLI"):
                self.run_setup()
        self.assertEqual(list(self.home.iterdir()), [])

    def test_json_stdout_contains_one_result(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            code = setup.main(
                ["--dry-run", "--json"],
                system=self.system,
                platform="darwin",
                home=self.home,
                environ={},
            )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "dry-run")
        self.assertEqual(list(self.home.iterdir()), [])

    def test_no_yes_and_no_controlling_terminal_does_not_consume_stdin(self):
        installer = self.installer()
        installer.args.yes = False
        with patch("builtins.open", side_effect=OSError("no tty")):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaisesRegex(setup.SetupError, "--yes"):
                    installer.setup()
        self.assertEqual(list(self.home.iterdir()), [])

    def test_human_output_is_a_short_readable_plan(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            code = setup.main(
                ["--dry-run"], system=self.system, platform="darwin", home=self.home, environ={}
            )
        self.assertEqual(code, 0)
        self.assertIn("Codex setup plan", output.getvalue())
        self.assertIn("plugin marketplace add", output.getvalue())
        self.assertNotIn('"commands":', output.getvalue())
        self.assertIn("no installation or recording settings were changed", output.getvalue())

    def test_no_persist_failure_restores_previous_owned_agent(self):
        installer, _ = self.run_setup()
        previous_agent = installer.launch_path.read_bytes()
        previous_state = installer.state_path.read_bytes()
        transition = self.installer("--no-persist")
        original_write = transition.atomic_bytes

        def fail_state(path, data, **kwargs):
            if path == transition.state_path:
                raise OSError("state disk full")
            return original_write(path, data, **kwargs)

        with patch.object(transition, "atomic_bytes", side_effect=fail_state):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaisesRegex(setup.SetupError, "disk full"):
                    transition.setup()
        self.assertEqual(installer.launch_path.read_bytes(), previous_agent)
        self.assertEqual(installer.state_path.read_bytes(), previous_state)

    def test_repeat_without_trace_root_preserves_previous_custom_directory(self):
        custom = self.home / "custom recordings"
        installer, _ = self.run_setup("--trace-root", str(custom))
        repeated, result = self.run_setup()
        self.assertEqual(repeated.trace_root, custom)
        self.assertEqual(result["status"], "unchanged")
        self.assertEqual(self.system.environment, str(custom))
        self.assertEqual(json.loads(installer.state_path.read_text())["traceRoot"], str(custom))

    def test_confirmation_time_launch_agent_edit_is_preserved(self):
        installer, _ = self.run_setup()
        second = self.installer()

        def concurrent_edit(plan):
            installer.launch_path.write_bytes(b"external edit during confirmation")

        with patch.object(second, "confirm", side_effect=concurrent_edit):
            with self.assertRaisesRegex(setup.SetupError, "changed since inspection"):
                second.setup()
        self.assertEqual(installer.launch_path.read_bytes(), b"external edit during confirmation")

    def test_confirmation_time_state_edit_is_preserved(self):
        installer, _ = self.run_setup()
        second = self.installer()
        modified = installer.state_path.read_bytes() + b" \n"
        with patch.object(
            second, "confirm", side_effect=lambda plan: installer.state_path.write_bytes(modified)
        ):
            with self.assertRaisesRegex(setup.SetupError, "changed since inspection"):
                second.setup()
        self.assertEqual(installer.state_path.read_bytes(), modified)

    def test_confirmation_time_environment_edit_is_preserved(self):
        installer = self.installer()
        with patch.object(
            installer,
            "confirm",
            side_effect=lambda plan: setattr(self.system, "environment", "/external"),
        ):
            with self.assertRaisesRegex(setup.SetupError, "environment changed"):
                installer.setup()
        self.assertEqual(self.system.environment, "/external")
        self.assertFalse(installer.launch_path.exists())

    def test_atomic_publish_compares_expected_bytes(self):
        installer = self.installer()
        target = self.home / "configuration"
        target.write_bytes(b"external edit")
        with self.assertRaisesRegex(setup.SetupError, "changed since inspection"):
            installer.atomic_bytes(target, b"replacement", expected=b"old value")
        self.assertEqual(target.read_bytes(), b"external edit")

    def test_corrupt_owned_state_is_a_controlled_error(self):
        installer = self.installer()
        installer.state_path.parent.mkdir(parents=True)
        for invalid in [
            {"owner": setup.OWNER, "stateVersion": 1, "client": "codex"},
            {"owner": setup.OWNER, "stateVersion": 1, "client": "codex", "traceRoot": []},
        ]:
            installer.state_path.write_text(json.dumps(invalid))
            with self.assertRaisesRegex(setup.SetupError, "unrecognized setup state"):
                installer.doctor()

    def test_doctor_reports_missing_or_edited_persistent_setup_as_needs_setup(self):
        installer, _ = self.run_setup()
        installer.launch_path.unlink()
        result = self.installer("doctor").doctor()
        self.assertEqual(result["status"], "needs-setup")
        self.assertEqual(result["launchAgent"], "missing-or-edited")
        installer.launch_path.write_bytes(b"user changed file")
        result = self.installer("doctor").doctor()
        self.assertEqual(result["status"], "needs-setup")


if __name__ == "__main__":
    unittest.main()
