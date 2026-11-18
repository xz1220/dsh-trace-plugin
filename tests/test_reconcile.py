"""Behavioral regressions for the development-only exact-scope reconciliation CLI."""

import argparse
import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import reconcile
import reconcile_fixture as fixture


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="reconciliation-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.sample = fixture.create(self.directory / "sample")
        self.capture = self.sample / "capture"
        self.output = self.directory / "report"
        self.args = argparse.Namespace(
            output=self.output,
            chat=self.sample / "chat.json",
            capture=[self.capture],
            thread_id=fixture.THREAD,
            turn_id=None,
            reader_dir=reconcile.DEFAULT_READER,
        )

    def check(self):
        with contextlib.redirect_stdout(io.StringIO()):
            code = reconcile.check(self.args)
        return code, json.loads((self.output / "report.json").read_text())

    def events(self):
        return [
            json.loads(line) for line in (self.capture / "trace.jsonl").read_text().splitlines()
        ]

    def write_events(self, events):
        (self.capture / "trace.jsonl").write_text(
            "".join(json.dumps(event) + "\n" for event in events)
        )

    def change_json(self, path, change):
        value = json.loads(path.read_text())
        change(value)
        path.write_text(json.dumps(value))

    def test_synthetic_ab_passes_and_report_omits_content(self):
        original = (self.capture / "trace.jsonl").read_bytes()
        fixture.append_b(self.sample)
        self.assertTrue((self.capture / "trace.jsonl").read_bytes().startswith(original))
        code, report = self.check()
        self.assertEqual(code, 0)
        self.assertEqual(report["counts"]["bug"], 0)
        self.assertEqual(report["counts"]["undetermined"], 0)
        self.assertTrue(
            any(item["reason"] == "explicit_turn_continuation" for item in report["items"])
        )
        self.assertEqual(report["counts"]["display_difference"], 1)
        self.assertTrue(report["provenance"]["reader"]["codeHashes"]["projection.py"])
        self.assertFalse(report["provenance"]["nativeDesktopAcceptance"])
        body = (self.output / "report.json").read_text() + (self.output / "report.md").read_text()
        self.assertNotIn(fixture.MARKERS["A"], body)
        self.assertNotIn("Print '", body)

    def test_source_present_reader_corruption_is_reader_bug(self):
        real_reader = reconcile.reader_snapshot

        def corrupt(*args):
            value = real_reader(*args)
            tool = next(item for item in value["items"] if item["kind"] == "tool")
            tool["value"]["output"] += "unexpected suffix"
            return value

        with patch.object(reconcile, "reader_snapshot", side_effect=corrupt):
            code, report = self.check()
        self.assertEqual(code, 1)
        bugs = [item for item in report["items"] if item["status"] == "bug"]
        self.assertEqual([(item["layer"], item["field"]) for item in bugs], [("reader", "output")])
        self.assertTrue(
            any(
                item["status"] == "matched"
                and item.get("field") == "output"
                and item["layer"] == "chat-source"
                for item in report["items"]
            )
        )

    def test_reader_exception_with_present_source_is_bug(self):
        with patch.object(reconcile, "reader_snapshot", side_effect=ValueError("injected")):
            code, report = self.check()
        self.assertEqual(code, 1)
        self.assertTrue(any(item["reason"] == "reader_error" for item in report["items"]))

    def test_missing_source_is_evidence_gap_not_reader_bug(self):
        event = next(
            event
            for event in reversed(self.events())
            if event["payload"]["type"] == "inference_completed"
        )
        path = self.capture / event["payload"]["response_payload"]["path"]
        self.change_json(path, lambda value: value.update(output_items=[]))
        code, report = self.check()
        self.assertEqual(code, 2)
        self.assertEqual(report["counts"]["bug"], 0)
        self.assertGreater(report["counts"]["source_missing"], 0)

    def test_unreadable_source_does_not_run_reader(self):
        event = next(
            event for event in self.events() if event["payload"]["type"] == "tool_call_ended"
        )
        (self.capture / event["payload"]["result_payload"]["path"]).unlink()
        with patch.object(reconcile, "reader_snapshot") as reader:
            code, report = self.check()
        reader.assert_not_called()
        self.assertEqual(code, 2)
        self.assertEqual(report["counts"]["bug"], 0)
        self.assertGreater(report["counts"]["source_unreadable"], 0)

    def test_wrong_thread_manifest_refuses_before_event_body(self):
        self.change_json(
            self.capture / "manifest.json",
            lambda value: value.update(root_thread_id="unrelated-thread"),
        )
        original = reconcile.io.safe_file
        seen = []

        def observe(root, relative):
            seen.append(relative)
            return original(root, relative)

        with (
            patch.object(reconcile.io, "safe_file", side_effect=observe),
            patch.object(reconcile, "reader_snapshot") as reader,
        ):
            code, report = self.check()
        reader.assert_not_called()
        self.assertNotIn("trace.jsonl", seen)
        self.assertFalse(any(str(path).startswith("payloads/") for path in seen))
        self.assertEqual(code, 2)
        self.assertEqual(report["items"][0]["reason"], "wrong_thread_manifest")

    def test_wrong_chat_thread_refuses_before_source(self):
        self.args.thread_id = "unrelated-thread"
        with patch.object(reconcile, "source_snapshot") as source:
            code, report = self.check()
        source.assert_not_called()
        self.assertEqual(code, 2)
        self.assertEqual(report["items"][0]["reason"], "wrong_thread_chat")

    def test_pending_event_tail_and_in_progress_do_not_pass(self):
        with (self.capture / "trace.jsonl").open("ab") as stream:
            stream.write(b'{"pending":')
        code, report = self.check()
        self.assertEqual(code, 2)
        self.assertTrue(any(item["reason"] == "pending_event_tail" for item in report["items"]))

    def test_unfinished_turn_does_not_pass_even_if_all_bodies_exist(self):
        self.change_json(
            self.args.chat, lambda value: value["turns"][0].update(status="inProgress")
        )
        code, report = self.check()
        self.assertEqual(code, 2)
        self.assertGreater(report["counts"]["undetermined"], 0)

    def test_unsafe_payload_reference_never_opens_outside_scope(self):
        events = self.events()
        event = next(event for event in events if event["payload"]["type"] == "inference_started")
        event["payload"]["request_payload"]["path"] = "../unrelated.json"
        self.write_events(events)
        code, report = self.check()
        self.assertEqual(code, 2)
        self.assertTrue(any(item["reason"] == "unsafe_payload_pointer" for item in report["items"]))

    def test_wrong_reader_turn_is_attribution_bug(self):
        real_reader = reconcile.reader_snapshot

        def corrupt(*args):
            value = real_reader(*args)
            next(item for item in value["items"] if item["kind"] == "final")["turnId"] = (
                "turn-other"
            )
            return value

        with patch.object(reconcile, "reader_snapshot", side_effect=corrupt):
            code, report = self.check()
        self.assertEqual(code, 1)
        self.assertTrue(
            any(item["status"] == "bug" and item.get("item") == "final" for item in report["items"])
        )

    def test_additional_wrong_turn_copy_is_bug(self):
        import copy

        fixture.append_b(self.sample)
        real_reader = reconcile.reader_snapshot

        def corrupt(*args):
            value = real_reader(*args)
            extra = copy.deepcopy(
                next(
                    item
                    for item in value["items"]
                    if item["kind"] == "final" and item["turnId"] == "turn-A"
                )
            )
            extra["turnId"] = "turn-B"
            value["items"].append(extra)
            return value

        with patch.object(reconcile, "reader_snapshot", side_effect=corrupt):
            code, report = self.check()
        self.assertEqual(code, 1)
        self.assertTrue(
            any(
                item["reason"] == "reader_extra_duplicate_or_wrong_turn" for item in report["items"]
            )
        )

    def test_failed_chat_tool_is_not_a_pass(self):
        def fail(value):
            value["turns"][0]["items"][1]["status"] = "failed"

        self.change_json(self.args.chat, fail)
        code, report = self.check()
        self.assertEqual(code, 2)
        self.assertTrue(
            any(item["reason"] == "terminal_not_successfully_completed" for item in report["items"])
        )

    def test_output_symlink_cannot_write_into_capture(self):
        target = self.capture / "empty"
        target.mkdir()
        alias = self.directory / "alias"
        alias.symlink_to(target, target_is_directory=True)
        self.args.output = alias
        with self.assertRaises(ValueError):
            self.check()
        self.assertEqual(list(target.iterdir()), [])

    def test_single_turn_without_predecessor_is_inconclusive(self):
        fixture.append_b(self.sample)
        self.args.turn_id = ["turn-B"]
        code, report = self.check()
        self.assertEqual(code, 2)
        self.assertEqual(report["counts"]["bug"], 0)
        self.assertTrue(
            any(
                item["reason"] == "predecessor_outside_supplied_evidence"
                for item in report["items"]
            )
        )

    def test_bad_reader_directory_is_configuration_evidence_gap(self):
        self.args.reader_dir = self.directory / "missing-reader"
        code, report = self.check()
        self.assertEqual(code, 2)
        self.assertEqual(report["counts"]["bug"], 0)
        self.assertEqual(report["items"][0]["layer"], "reader-configuration")

    def test_unreadable_chat_writes_nonpassing_reports(self):
        self.args.chat.unlink()
        code, report = self.check()
        self.assertEqual(code, 2)
        self.assertGreater(report["counts"]["source_unreadable"], 0)
        self.assertTrue((self.output / "report.md").is_file())

    def test_cli_detects_injected_error_in_selected_reader(self):
        copied_reader = self.directory / "faulty-reader"
        shutil.copytree(
            reconcile.DEFAULT_READER, copied_reader, ignore=shutil.ignore_patterns("__pycache__")
        )
        with (copied_reader / "store.py").open("a") as stream:
            stream.write("""
_original_reconciliation_cell_text = Store.cell_text

def _injected_reconciliation_cell_text(self, trace_id, row_id, cell_key, field, *args, **kwargs):
    result = _original_reconciliation_cell_text(self, trace_id, row_id, cell_key, field, *args, **kwargs)
    if cell_key == "tool" and field == "outputDetail" and result.get("available"):
        result = dict(result, text=result["text"] + "CORRUPTED", totalChars=result["totalChars"] + 9)
    return result

Store.cell_text = _injected_reconciliation_cell_text
""")
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/reconcile.py"),
                "check",
                "--chat",
                str(self.args.chat),
                "--capture",
                str(self.capture),
                "--thread-id",
                fixture.THREAD,
                "--reader-dir",
                str(copied_reader),
                "--output",
                str(self.output),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        report = json.loads((self.output / "report.json").read_text())
        self.assertTrue(
            any(
                item["status"] == "bug"
                and item.get("layer") == "reader"
                and item.get("field") == "output"
                for item in report["items"]
            )
        )
        self.assertEqual(report["counts"]["source_missing"], 0)
        self.assertEqual(report["counts"]["source_unreadable"], 0)
        self.assertEqual(report["provenance"]["reader"]["readerDir"], str(copied_reader.resolve()))

    def test_cli_entry_point_and_owned_output_guard(self):
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/reconcile.py"),
                "check",
                "--chat",
                str(self.args.chat),
                "--capture",
                str(self.capture),
                "--thread-id",
                fixture.THREAD,
                "--output",
                str(self.output),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["result"], "passed")
        unrelated = self.directory / "unrelated"
        unrelated.mkdir()
        (unrelated / "keep.txt").write_text("preserve")
        self.args.output = unrelated
        with self.assertRaises(ValueError):
            self.check()
        self.assertEqual((unrelated / "keep.txt").read_text(), "preserve")


if __name__ == "__main__":
    unittest.main()
