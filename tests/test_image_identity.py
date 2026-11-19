"""Images in separate output messages retain distinct content identities."""

import base64
import sys
import unittest
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/codex-dsh-trace/server"))

from projection import source_blocks
from projection_fixture import ProjectionFixture


def image(color, encoded=False):
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"><rect width="1" height="1" fill="{color}"/></svg>'
    if encoded:
        return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()
    return "data:image/svg+xml," + quote(svg)


class ImageIdentityTests(ProjectionFixture, unittest.TestCase):
    def test_non_base64_images_in_separate_output_messages_do_not_alias(self):
        request = self.fixture.payload({"input": []}, "inference_request")
        self.fixture.append(
            "inference_started", inference_call_id="images", request_payload=request
        )
        urls = [image("red"), image("blue")]
        response = self.fixture.payload(
            {
                "output_items": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_image", "image_url": url}],
                    }
                    for url in urls
                ]
            },
            "inference_response",
        )
        self.fixture.append(
            "inference_completed", inference_call_id="images", response_payload=response
        )
        projector = self.project()
        metadata = next(
            cell for cell in projector.page()["cells"] if cell["cellKey"] == "assistant"
        )
        pending = [block["attachment"] for block in metadata["sourceBlocks"]]
        self.assertNotEqual(pending[0]["attachmentId"], pending[1]["attachmentId"])
        self.assertTrue(all("recordedUrl" not in attachment for attachment in pending))
        detail = projector.detail("request:images", "assistant")
        attachments = [block["attachment"] for block in detail["sourceBlocks"]]
        self.assertEqual([value["recordedUrl"] for value in attachments], urls)
        self.assertNotEqual(attachments[0]["attachmentId"], attachments[1]["attachmentId"])

    def test_inline_identity_follows_content_across_rows_and_revisions(self):
        def attachment(url, owner):
            return source_blocks(
                {"content": [{"type": "image", "image_url": url}]}, owner, "output"
            )[0]["attachment"]

        for encoded in (False, True):
            with self.subTest(base64=encoded):
                before = attachment(image("red", encoded), "old")
                same = attachment(image("red", encoded), "other")
                changed = attachment(image("blue", encoded), "old")
                self.assertEqual(before["attachmentId"], same["attachmentId"])
                self.assertNotEqual(before["attachmentId"], changed["attachmentId"])

    def test_metadata_and_unrecorded_urls_do_not_expose_inline_bytes(self):
        url = image("red")
        blocks = source_blocks(
            {"content": [{"type": "image", "image_url": url}]}, "row", "output", metadata_only=True
        )
        self.assertNotIn("recordedUrl", blocks[0]["attachment"])
        remote = source_blocks(
            {"content": [{"type": "image", "image_url": "https://example.invalid/image"}]},
            "row",
            "output",
        )
        self.assertNotIn("recordedUrl", remote[0]["attachment"])

    def test_inline_image_size_is_decoded_bytes_and_unknown_is_not_zero(self):
        payload = '<svg xmlns="http://www.w3.org/2000/svg"><text>鸟+%</text></svg>'
        raw = payload.encode("utf-8")
        encoded = quote(payload)
        self.assertNotEqual(len(raw), len(payload))
        self.assertNotEqual(len(raw), len(encoded))
        urls = [
            "data:image/svg+xml," + encoded,
            "data:image/svg+xml;base64," + base64.b64encode(raw).decode(),
        ]
        for url in urls:
            with self.subTest(url=url):
                attachment = source_blocks(
                    {"content": [{"type": "image", "image_url": url}]}, "row", "output"
                )[0]["attachment"]
                self.assertEqual(attachment["bytes"], len(raw))
                self.assertEqual(attachment["recordedUrl"], url)
        for url in (
            "data:image/png;base64,not!base64",
            "data:image/png",
            "https://example.invalid/image",
        ):
            with self.subTest(unknown=url):
                attachment = source_blocks(
                    {"content": [{"type": "image", "image_url": url}]}, "row", "output"
                )[0]["attachment"]
                self.assertNotIn("bytes", attachment)

    def test_uppercase_base64_header_resolves_content_hash_and_png_dimensions(self):
        # Minimal PNG signature + IHDR chunk (32x18 pixels).
        png_bytes = (
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\x0dIHDR"
            + (32).to_bytes(4, "big")
            + (18).to_bytes(4, "big")
            + b"\x08\x02\x00\x00\x00"
        )
        encoded = base64.b64encode(png_bytes).decode()
        lower = source_blocks(
            {"content": [{"type": "image", "image_url": f"data:image/png;base64,{encoded}"}]},
            "row",
            "output",
        )[0]["attachment"]
        upper = source_blocks(
            {"content": [{"type": "image", "image_url": f"data:image/png;BASE64,{encoded}"}]},
            "row",
            "output",
        )[0]["attachment"]
        self.assertEqual(upper["attachmentId"], lower["attachmentId"])
        self.assertEqual(upper["bytes"], len(png_bytes))
        self.assertEqual((upper["width"], upper["height"]), (32, 18))
