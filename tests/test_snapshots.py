"""Paging stays bound to the content selected before live history changes."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/codex-dsh-trace/server"))

from fixtures import Fixture
from snapshots import Snapshots
from store import CHUNK, Store, TraceError


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        isolated = patch.dict(os.environ, {"CODEX_ROLLOUT_TRACE_ROOT": str(self.root / "none")})
        isolated.start()
        self.addCleanup(isolated.stop)
        self.store = Store(self.root / "config.json")
        self.store.catalog.default_root = self.root / "none"
        self.store.catalog.register(str(self.root))

    def bundle(self, name, started_at=1000):
        fixture = Fixture(self.root / name, schema_version=2, started_at=started_at)
        path = fixture.root / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["trace_id"] = name
        path.write_text(json.dumps(manifest))
        self.store.catalog.last_scan = None
        return fixture

    @staticmethod
    def message(role, text):
        return {
            "type": "message",
            "role": role,
            "content": [{"type": "input_text" if role == "user" else "output_text", "text": text}],
        }

    def request(self, fixture, name, inputs=None, previous=None):
        raw = {"input": inputs or []}
        if previous:
            raw["previous_response_id"] = previous
        ref = fixture.payload(raw, "inference_request")
        fixture.append("inference_started", inference_call_id=name, request_payload=ref)

    def response(self, fixture, name, text, response_id=None):
        ref = fixture.payload(
            {"output_items": [self.message("assistant", text)]}, "inference_response"
        )
        fixture.append(
            "inference_completed",
            inference_call_id=name,
            response_id=response_id or "response-" + name,
            response_payload=ref,
        )

    def finish_text(self, first, trace, row, section, item_index=None):
        text = first["text"]
        offset = first["nextOffset"]
        while offset is not None:
            page = self.store.text(
                trace,
                row,
                section,
                item_index=item_index,
                offset=offset,
                snapshot=first["snapshot"],
            )
            self.assertEqual(page["snapshot"], first["snapshot"])
            text += page["text"]
            offset = page["nextOffset"]
        return text

    def assert_content_updated(self, action):
        with self.assertRaises(TraceError) as error:
            action()
        self.assertEqual(error.exception.code, "content_updated")

    def test_context_pages_finish_the_original_snapshot_when_older_recording_is_discovered(self):
        later = self.bundle("later", 5000)
        current = "CURRENT 🌱" * 8000
        inherited = "EARLIER 🌿" * 8000
        self.request(later, "child", [self.message("user", current)], previous="parent-response")
        trace, row = "thread@thread-root", "later:request:child"
        first = self.store.text(trace, row, "full_context")
        self.assertIsNotNone(first["nextOffset"])

        older = self.bundle("older", 1000)
        self.request(older, "parent", [self.message("user", inherited)])
        self.response(older, "parent", "Recorded answer", response_id="parent-response")
        self.store.binding("thread-root")

        self.assertEqual(self.finish_text(first, trace, row, "full_context"), "[user]\n" + current)
        fresh = self.store.text(trace, row, "full_context")
        self.assertNotEqual(fresh["snapshot"], first["snapshot"])
        self.assertEqual(
            self.finish_text(fresh, trace, row, "full_context"),
            f"[user]\n{inherited}\n\n[assistant]\nRecorded answer\n\n[user]\n{current}",
        )

    def test_text_snapshot_cannot_be_reused_for_another_row_section_or_message(self):
        fixture = self.bundle("one")
        self.request(
            fixture, "first", [self.message("user", "First"), self.message("user", "Second")]
        )
        self.request(fixture, "second")
        first = self.store.text("one", "request:first", "message", item_index=0)
        for row, section, position in (
            ("request:second", "message", 0),
            ("request:first", "message_json", 0),
            ("request:first", "message", 1),
        ):
            with self.subTest(row=row, section=section, position=position):
                self.assert_content_updated(
                    lambda: self.store.text(
                        "one", row, section, item_index=position, snapshot=first["snapshot"]
                    )
                )

    def test_large_cell_is_built_once_for_all_66_pages(self):
        fixture = self.bundle("large")
        self.request(fixture, "first")
        content = "X" * (3 * 1024 * 1024)
        self.response(fixture, "first", content)
        projector = self.store.projection("large")
        with patch.object(projector, "build_detail", wraps=projector.build_detail) as build:
            metadata = self.store.cell_detail("large", "request:first", "assistant")
            pieces = []
            offset = 0
            while offset is not None:
                page = self.store.cell_text(
                    "large",
                    "request:first",
                    "assistant",
                    "outputDetail",
                    offset=offset,
                    snapshot=metadata["snapshot"],
                )
                pieces.append(page["text"])
                offset = page["nextOffset"]
            self.assertEqual(build.call_count, 1)
        self.assertEqual(len(pieces), 66)
        self.assertEqual("".join(pieces), content)

    def test_cell_snapshot_is_bound_to_its_row_cell_and_fields(self):
        fixture = self.bundle("one")
        self.request(fixture, "first")
        self.response(fixture, "first", "Recorded")
        metadata = self.store.cell_detail("one", "request:first", "assistant")
        for trace, row, cell, field in (
            ("other", "request:first", "assistant", "outputDetail"),
            ("one", "request:other", "assistant", "outputDetail"),
            ("one", "request:first", "prompt", "outputDetail"),
            ("one", "request:first", "assistant", "not-a-field"),
        ):
            with self.subTest(trace=trace, row=row, cell=cell, field=field):
                self.assert_content_updated(
                    lambda: self.store.cell_text(
                        trace, row, cell, field, snapshot=metadata["snapshot"]
                    )
                )

    def test_eviction_returns_content_updated_in_both_paging_apis(self):
        self.store.snapshots = Snapshots(max_entries=1)
        fixture = self.bundle("one")
        self.request(fixture, "first", [self.message("user", "Original")])
        self.response(fixture, "first", "Answer")
        first = self.store.text("one", "request:first", "full_context")
        metadata = self.store.cell_detail("one", "request:first", "assistant")
        self.assert_content_updated(
            lambda: self.store.text(
                "one", "request:first", "full_context", snapshot=first["snapshot"]
            )
        )
        self.store.text("one", "request:first", "full_context")
        self.assert_content_updated(
            lambda: self.store.cell_text(
                "one", "request:first", "assistant", "outputDetail", snapshot=metadata["snapshot"]
            )
        )

    def test_rebuilt_epoch_with_the_same_numeric_version_does_not_change_old_snapshot(self):
        fixture = self.bundle("one")
        self.request(fixture, "first")
        original = "A" * (CHUNK + 20)
        self.response(fixture, "first", original)
        metadata = self.store.cell_detail("one", "request:first", "assistant")
        index = self.store.index("one")
        epoch = index.epoch

        (fixture.root / "trace.jsonl").write_text("")
        fixture.seq = 0
        self.request(fixture, "first")
        changed = "B" * len(original)
        self.response(fixture, "first", changed)
        log = fixture.root / "trace.jsonl"
        replacement = log.with_suffix(".replacement")
        replacement.write_bytes(log.read_bytes())
        replacement.replace(log)

        fresh = self.store.cell_detail("one", "request:first", "assistant")
        self.assertNotEqual(index.epoch, epoch)
        self.assertEqual(metadata["cell"]["version"], fresh["cell"]["version"])
        for selected, expected in ((metadata, original), (fresh, changed)):
            with self.subTest(snapshot=selected["snapshot"]):
                head = self.store.cell_text(
                    "one",
                    "request:first",
                    "assistant",
                    "outputDetail",
                    snapshot=selected["snapshot"],
                )
                tail = self.store.cell_text(
                    "one",
                    "request:first",
                    "assistant",
                    "outputDetail",
                    offset=head["nextOffset"],
                    snapshot=selected["snapshot"],
                )
                self.assertEqual(head["text"] + tail["text"], expected)

    def test_legacy_version_parameter_still_rejects_changed_live_content(self):
        fixture = self.bundle("one")
        self.request(fixture, "first")
        self.response(fixture, "first", "Original")
        metadata = self.store.cell_detail("one", "request:first", "assistant")
        version = metadata["cell"]["version"]
        before = self.store.cell_text(
            "one", "request:first", "assistant", "outputDetail", version=version
        )
        self.assertEqual(before["text"], "Original")
        self.response(fixture, "first", "Changed")
        self.assert_content_updated(
            lambda: self.store.cell_text(
                "one", "request:first", "assistant", "outputDetail", version=version
            )
        )


if __name__ == "__main__":
    unittest.main()
