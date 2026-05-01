import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ui_island.services import resource_metadata


class ResourceMetadataTests(unittest.TestCase):
    def test_ensure_metadata_merges_runtime_enable_versions(self) -> None:
        payload = {}
        with patch("config.APP_ENABLE_VERSIONS", ["0.1.2", "0.1.3"], create=True):
            resource_metadata.ensure_metadata(payload, include_route_defaults=True)

        self.assertEqual(payload["enable_versions"][:2], ["0.1.2", "0.1.3"])
        self.assertIn(resource_metadata.APP_FORMAT_VERSION, payload["enable_versions"])

    def test_ensure_metadata_keeps_route_defaults_only(self) -> None:
        payload = {"loop": "yes", "notes": 123}

        resource_metadata.ensure_metadata(payload, include_route_defaults=True)

        self.assertTrue(payload["loop"])
        self.assertEqual(payload["notes"], "123")

    def test_ensure_metadata_can_preserve_existing_route_metadata(self) -> None:
        payload = {
            "format_version": "old-format",
            "enable_versions": ["old-format", resource_metadata.APP_FORMAT_VERSION],
            "loop": "yes",
        }

        resource_metadata.ensure_metadata(
            payload,
            include_route_defaults=True,
            preserve_format_version=True,
            enable_versions_policy="append_current_if_list",
        )

        self.assertEqual(payload["format_version"], "old-format")
        self.assertEqual(payload["enable_versions"], ["old-format", resource_metadata.APP_FORMAT_VERSION])
        self.assertTrue(payload["loop"])

    def test_ensure_metadata_preserve_mode_does_not_create_missing_enable_versions(self) -> None:
        payload = {"notes": None}

        resource_metadata.ensure_metadata(
            payload,
            include_route_defaults=True,
            preserve_format_version=True,
            enable_versions_policy="append_current_if_list",
        )

        self.assertNotIn("format_version", payload)
        self.assertNotIn("enable_versions", payload)
        self.assertEqual(payload["notes"], "")

    def test_read_annotation_enable_versions_dedupes_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "points.json")
            path.write_text(
                json.dumps({"enable_versions": [" 1.0.0 ", "", "1.0.0", "2.0.0"]}),
                encoding="utf-8",
            )

            self.assertEqual(resource_metadata.read_annotation_enable_versions(path), ["1.0.0", "2.0.0"])

    def test_write_annotation_enable_versions_preserves_format_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "points.json")
            path.write_text(
                json.dumps(
                    {
                        "format_version": "publisher-format",
                        "enable_versions": ["old"],
                        "pointsByType": {"ore": [{"x": 1, "y": 2}]},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            self.assertTrue(resource_metadata.write_annotation_enable_versions(path, [" 1.0.0 ", "1.0.0"]))

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["format_version"], "publisher-format")
            self.assertEqual(payload["enable_versions"], ["publisher-format", "1.0.0"])
            self.assertEqual(payload["pointsByType"], {"ore": [{"x": 1, "y": 2}]})

    def test_write_annotation_enable_versions_keeps_empty_array(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "points.json")
            path.write_text(
                json.dumps({"format_version": "publisher-format", "enable_versions": ["old"]}),
                encoding="utf-8",
            )

            self.assertTrue(resource_metadata.write_annotation_enable_versions(path, []))

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["format_version"], "publisher-format")
            self.assertEqual(payload["enable_versions"], ["publisher-format"])

    def test_write_annotation_enable_versions_keeps_empty_array_without_format_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "points.json")
            path.write_text(
                json.dumps({"enable_versions": ["old"]}),
                encoding="utf-8",
            )

            self.assertTrue(resource_metadata.write_annotation_enable_versions(path, []))

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("format_version", payload)
            self.assertEqual(payload["enable_versions"], [])


if __name__ == "__main__":
    unittest.main()
