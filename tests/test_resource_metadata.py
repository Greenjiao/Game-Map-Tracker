import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ui_island.services import resource_metadata


class ResourceMetadataTests(unittest.TestCase):
    def test_default_point_layer_reads_mapping_and_reloads_after_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            maps_dir = Path(tmp) / "maps"
            maps_dir.mkdir()
            mapping = maps_dir / "layer_maps.json"
            mapping.write_text(json.dumps({"default_layer": "地表"}), encoding="utf-8")

            self.assertEqual(resource_metadata.default_point_layer(tmp), "地表")

            mapping.write_text(json.dumps({"default_layer": "新地表"}), encoding="utf-8")
            self.assertEqual(resource_metadata.default_point_layer(tmp), "新地表")

    def test_default_point_layer_is_empty_when_mapping_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(resource_metadata.default_point_layer(tmp), "")

    def test_point_layer_or_default_preserves_nonempty_layer_and_fills_empty_value(self) -> None:
        with patch.object(resource_metadata, "default_point_layer", return_value="地表"):
            self.assertEqual(resource_metadata.point_layer_or_default("  地下层  "), "地下层")
            self.assertEqual(resource_metadata.point_layer_or_default(""), "地表")
            self.assertEqual(resource_metadata.point_layer_or_default(None), "地表")

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


if __name__ == "__main__":
    unittest.main()
