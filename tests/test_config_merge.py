import json
import tempfile
import unittest
from pathlib import Path

import config


class ConfigMergeTests(unittest.TestCase):
    def test_merge_adds_new_fields_and_preserves_user_values(self) -> None:
        defaults = {
            "CONFIG_VERSION": 2,
            "WINDOW_GEOMETRY": {"x": 0, "y": 0, "width": 420, "height": 360},
            "SIDEBAR_WIDTH": 270,
            "NESTED": {"old": 1, "new": 2},
        }
        user = {
            "CONFIG_VERSION": 1,
            "WINDOW_GEOMETRY": {"x": 99, "y": 88},
            "SIDEBAR_WIDTH": 333,
            "NESTED": {"old": 9},
            "LEGACY_KEY": "keep me",
        }

        merged, repaired = config.merge_config_payload(defaults, user)

        self.assertEqual(repaired, [])
        self.assertEqual(merged["CONFIG_VERSION"], 2)
        self.assertEqual(merged["WINDOW_GEOMETRY"], {"x": 99, "y": 88, "width": 420, "height": 360})
        self.assertEqual(merged["SIDEBAR_WIDTH"], 333)
        self.assertEqual(merged["NESTED"], {"old": 9, "new": 2})
        self.assertEqual(merged["LEGACY_KEY"], "keep me")

    def test_merge_repairs_obviously_wrong_types(self) -> None:
        defaults = {
            "CONFIG_VERSION": 2,
            "SIDEBAR_COLLAPSED": True,
            "SIDEBAR_WIDTH": 270,
            "SIFT_CLAHE_LIMIT": 3.0,
            "MINIMAP": {},
        }
        user = {
            "CONFIG_VERSION": "old",
            "SIDEBAR_COLLAPSED": "yes",
            "SIDEBAR_WIDTH": "wide",
            "SIFT_CLAHE_LIMIT": 2,
            "MINIMAP": [],
        }

        merged, repaired = config.merge_config_payload(defaults, user)

        self.assertEqual(merged["CONFIG_VERSION"], 2)
        self.assertEqual(merged["SIDEBAR_COLLAPSED"], True)
        self.assertEqual(merged["SIDEBAR_WIDTH"], 270)
        self.assertEqual(merged["SIFT_CLAHE_LIMIT"], 2)
        self.assertEqual(merged["MINIMAP"], {})
        self.assertIn("SIDEBAR_COLLAPSED", repaired)
        self.assertIn("SIDEBAR_WIDTH", repaired)
        self.assertIn("MINIMAP", repaired)

    def test_route_color_settings_are_merged_and_repaired(self) -> None:
        merged, _repaired = config.merge_config_payload(config.DEFAULT_CONFIG, {"CONFIG_VERSION": 2})

        self.assertEqual(merged["ROUTE_MULTI_COLOR_ENABLED"], True)
        self.assertEqual(merged["ROUTE_DEFAULT_COLOR"], "#1ad1ff")
        self.assertEqual(merged["ROUTE_TELEPORT_LINE_COLOR"], "#ffffff")
        self.assertEqual(merged["ROUTE_GUIDE_LINE_COLOR"], "#ffffff")
        self.assertEqual(merged["ROUTE_POINTER_ARROW_COLOR"], "#000000")
        self.assertEqual(merged["ROUTE_POINTER_ARROW_VISIBLE"], True)
        self.assertEqual(merged["ROUTE_SPECIAL_LINES_FOLLOW_ROUTE_COLOR"], False)
        self.assertEqual(merged["ROUTE_STRICT_GUIDE_MODE"], False)
        self.assertEqual(merged["ROUTE_VISITED_POINT_OPACITY"], 1.0)
        self.assertEqual(merged["ROUTE_VISITED_ICON_OPACITY"], 0.35)
        self.assertEqual(merged["WINDOW_LOCKED_OPACITY"], 0.78)
        self.assertEqual(merged["WINDOW_NORMAL_OPACITY"], 1.0)

        user = {
            "CONFIG_VERSION": 2,
            "ROUTE_MULTI_COLOR_ENABLED": False,
            "ROUTE_DEFAULT_COLOR": "#abc123",
            "ROUTE_TELEPORT_LINE_COLOR": "#ffffff",
            "ROUTE_GUIDE_LINE_COLOR": "#eeeeee",
            "ROUTE_POINTER_ARROW_COLOR": "#000000",
            "ROUTE_POINTER_ARROW_VISIBLE": False,
            "ROUTE_SPECIAL_LINES_FOLLOW_ROUTE_COLOR": True,
            "ROUTE_STRICT_GUIDE_MODE": True,
        }
        merged, repaired = config.merge_config_payload(config.DEFAULT_CONFIG, user)

        self.assertEqual(repaired, [])
        self.assertEqual(merged["ROUTE_MULTI_COLOR_ENABLED"], False)
        self.assertEqual(merged["ROUTE_DEFAULT_COLOR"], "#abc123")
        self.assertEqual(merged["ROUTE_TELEPORT_LINE_COLOR"], "#ffffff")
        self.assertEqual(merged["ROUTE_GUIDE_LINE_COLOR"], "#eeeeee")
        self.assertEqual(merged["ROUTE_POINTER_ARROW_COLOR"], "#000000")
        self.assertEqual(merged["ROUTE_POINTER_ARROW_VISIBLE"], False)
        self.assertEqual(merged["ROUTE_SPECIAL_LINES_FOLLOW_ROUTE_COLOR"], True)
        self.assertEqual(merged["ROUTE_STRICT_GUIDE_MODE"], True)

        user = {
            "CONFIG_VERSION": 2,
            "ROUTE_MULTI_COLOR_ENABLED": "false",
            "ROUTE_DEFAULT_COLOR": 123,
            "ROUTE_TELEPORT_LINE_COLOR": 123,
            "ROUTE_GUIDE_LINE_COLOR": [],
            "ROUTE_POINTER_ARROW_COLOR": {},
            "ROUTE_POINTER_ARROW_VISIBLE": "no",
            "ROUTE_SPECIAL_LINES_FOLLOW_ROUTE_COLOR": "yes",
            "ROUTE_STRICT_GUIDE_MODE": "yes",
        }
        merged, repaired = config.merge_config_payload(config.DEFAULT_CONFIG, user)

        self.assertEqual(merged["ROUTE_MULTI_COLOR_ENABLED"], True)
        self.assertEqual(merged["ROUTE_DEFAULT_COLOR"], "#1ad1ff")
        self.assertEqual(merged["ROUTE_TELEPORT_LINE_COLOR"], "#ffffff")
        self.assertEqual(merged["ROUTE_GUIDE_LINE_COLOR"], "#ffffff")
        self.assertEqual(merged["ROUTE_POINTER_ARROW_COLOR"], "#000000")
        self.assertEqual(merged["ROUTE_POINTER_ARROW_VISIBLE"], True)
        self.assertEqual(merged["ROUTE_SPECIAL_LINES_FOLLOW_ROUTE_COLOR"], False)
        self.assertEqual(merged["ROUTE_STRICT_GUIDE_MODE"], False)
        self.assertIn("ROUTE_MULTI_COLOR_ENABLED", repaired)
        self.assertIn("ROUTE_DEFAULT_COLOR", repaired)
        self.assertIn("ROUTE_TELEPORT_LINE_COLOR", repaired)
        self.assertIn("ROUTE_GUIDE_LINE_COLOR", repaired)
        self.assertIn("ROUTE_POINTER_ARROW_COLOR", repaired)
        self.assertIn("ROUTE_POINTER_ARROW_VISIBLE", repaired)
        self.assertIn("ROUTE_SPECIAL_LINES_FOLLOW_ROUTE_COLOR", repaired)
        self.assertIn("ROUTE_STRICT_GUIDE_MODE", repaired)

        user = {
            "CONFIG_VERSION": 2,
            "ROUTE_VISITED_POINT_OPACITY": "solid",
            "ROUTE_VISITED_ICON_OPACITY": [],
            "WINDOW_LOCKED_OPACITY": None,
            "WINDOW_NORMAL_OPACITY": {},
        }
        merged, repaired = config.merge_config_payload(config.DEFAULT_CONFIG, user)

        self.assertEqual(merged["ROUTE_VISITED_POINT_OPACITY"], 1.0)
        self.assertEqual(merged["ROUTE_VISITED_ICON_OPACITY"], 0.35)
        self.assertEqual(merged["WINDOW_LOCKED_OPACITY"], 0.78)
        self.assertEqual(merged["WINDOW_NORMAL_OPACITY"], 1.0)
        self.assertIn("ROUTE_VISITED_POINT_OPACITY", repaired)
        self.assertIn("ROUTE_VISITED_ICON_OPACITY", repaired)
        self.assertIn("WINDOW_LOCKED_OPACITY", repaired)
        self.assertIn("WINDOW_NORMAL_OPACITY", repaired)

    def test_toggle_lock_hotkey_settings_are_merged_and_repaired(self) -> None:
        merged, _repaired = config.merge_config_payload(config.DEFAULT_CONFIG, {"CONFIG_VERSION": 2})

        self.assertEqual(
            merged["TOGGLE_LOCK_HOTKEY"],
            {
                "sequence": "Alt+`",
                "label": "Alt+`",
                "modifiers": ["Alt"],
                "key": "QuoteLeft",
                "vk": 0xC0,
            },
        )

        user = {
            "CONFIG_VERSION": 2,
            "TOGGLE_LOCK_HOTKEY": {
                "sequence": "Ctrl+Alt+L",
                "label": "Ctrl+Alt+L",
                "modifiers": ["Ctrl", "Alt"],
                "key": "L",
                "vk": 0x4C,
            },
        }
        merged, repaired = config.merge_config_payload(config.DEFAULT_CONFIG, user)

        self.assertEqual(repaired, [])
        self.assertEqual(merged["TOGGLE_LOCK_HOTKEY"]["label"], "Ctrl+Alt+L")
        self.assertEqual(merged["TOGGLE_LOCK_HOTKEY"]["vk"], 0x4C)

        merged, repaired = config.merge_config_payload(
            config.DEFAULT_CONFIG,
            {"CONFIG_VERSION": 2, "TOGGLE_LOCK_HOTKEY": "Alt+`"},
        )

        self.assertEqual(merged["TOGGLE_LOCK_HOTKEY"], config.DEFAULT_CONFIG["TOGGLE_LOCK_HOTKEY"])
        self.assertIn("TOGGLE_LOCK_HOTKEY", repaired)

    def test_annotation_group_expanded_is_merged_and_repaired(self) -> None:
        merged, _repaired = config.merge_config_payload(config.DEFAULT_CONFIG, {"CONFIG_VERSION": 2})

        self.assertEqual(merged["ANNOTATION_GROUP_EXPANDED"], {})

        merged, repaired = config.merge_config_payload(
            config.DEFAULT_CONFIG,
            {"CONFIG_VERSION": 2, "ANNOTATION_GROUP_EXPANDED": {"采集物": False}},
        )

        self.assertEqual(repaired, [])
        self.assertEqual(merged["ANNOTATION_GROUP_EXPANDED"], {"采集物": False})

        merged, repaired = config.merge_config_payload(
            config.DEFAULT_CONFIG,
            {"CONFIG_VERSION": 2, "ANNOTATION_GROUP_EXPANDED": []},
        )

        self.assertEqual(merged["ANNOTATION_GROUP_EXPANDED"], {})
        self.assertIn("ANNOTATION_GROUP_EXPANDED", repaired)

    def test_runtime_remote_config_fields_are_removed_from_config_json(self) -> None:
        user = {
            "CONFIG_VERSION": 2,
            "QUARK_DOWNLOAD_URL": "https://example.com/quark",
            "ROUTE_RESOURCE_URL": "https://example.com/routes",
            "DOCUMENTATION_URL": "https://example.com/docs",
            "FEEDBACK_BILIBILI_URL": "https://space.bilibili.com/example",
            "FEEDBACK_QQ_GROUP": "123456789",
            "APP_UPDATE_MANIFEST_URL": "https://example.com/app-manifest.json",
            "APP_UPDATE_MANIFEST_URLS": ["https://example.com/app-manifest.json"],
        }
        merged, repaired = config.merge_config_payload(config.DEFAULT_CONFIG, user)

        self.assertNotIn("QUARK_DOWNLOAD_URL", merged)
        self.assertNotIn("ROUTE_RESOURCE_URL", merged)
        self.assertNotIn("DOCUMENTATION_URL", merged)
        self.assertNotIn("FEEDBACK_BILIBILI_URL", merged)
        self.assertNotIn("FEEDBACK_QQ_GROUP", merged)
        self.assertNotIn("APP_UPDATE_MANIFEST_URL", merged)
        self.assertNotIn("APP_UPDATE_MANIFEST_URLS", merged)
        self.assertIn("QUARK_DOWNLOAD_URL", repaired)
        self.assertIn("ROUTE_RESOURCE_URL", repaired)
        self.assertIn("DOCUMENTATION_URL", repaired)
        self.assertIn("FEEDBACK_BILIBILI_URL", repaired)
        self.assertIn("FEEDBACK_QQ_GROUP", repaired)
        self.assertIn("APP_UPDATE_MANIFEST_URL", repaired)
        self.assertIn("APP_UPDATE_MANIFEST_URLS", repaired)

    def test_route_recent_limit_is_removed_as_obsolete_config(self) -> None:
        self.assertNotIn("ROUTE_RECENT_LIMIT", config.DEFAULT_CONFIG)

        merged, repaired = config.merge_config_payload(
            config.DEFAULT_CONFIG,
            {"CONFIG_VERSION": 2, "ROUTE_RECENT_LIMIT": 8},
        )

        self.assertNotIn("ROUTE_RECENT_LIMIT", merged)
        self.assertIn("ROUTE_RECENT_LIMIT", repaired)

    def test_annotation_recent_type_ids_is_removed_as_obsolete_config(self) -> None:
        self.assertNotIn("ANNOTATION_RECENT_TYPE_IDS", config.DEFAULT_CONFIG)

        merged, repaired = config.merge_config_payload(
            config.DEFAULT_CONFIG,
            {"CONFIG_VERSION": 2, "ANNOTATION_RECENT_TYPE_IDS": ["a-1"]},
        )

        self.assertNotIn("ANNOTATION_RECENT_TYPE_IDS", merged)
        self.assertIn("ANNOTATION_RECENT_TYPE_IDS", repaired)

    def test_merge_config_payload_accepts_extra_obsolete_keys(self) -> None:
        defaults = {"CONFIG_VERSION": 2, "SIDEBAR_WIDTH": 270}
        user = {
            "CONFIG_VERSION": 2,
            "SIDEBAR_WIDTH": 333,
            "REMOVED_BY_MANIFEST": "old",
            "UNKNOWN_BUT_ALLOWED": "keep",
        }

        merged, repaired = config.merge_config_payload(
            defaults,
            user,
            obsolete_config_keys=("REMOVED_BY_MANIFEST",),
        )

        self.assertEqual(merged["SIDEBAR_WIDTH"], 333)
        self.assertNotIn("REMOVED_BY_MANIFEST", merged)
        self.assertEqual(merged["UNKNOWN_BUT_ALLOWED"], "keep")
        self.assertIn("REMOVED_BY_MANIFEST", repaired)

    def test_merge_config_file_backs_up_and_rewrites_corrupt_json(self) -> None:
        defaults = {"CONFIG_VERSION": 2, "SIDEBAR_WIDTH": 270}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text("{broken", encoding="utf-8")

            merged = config.merge_config_file(str(path), defaults)

            self.assertEqual(merged, defaults)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), defaults)
            self.assertEqual((Path(str(path) + ".bak")).read_text(encoding="utf-8"), "{broken")

    def test_merge_config_file_backs_up_before_writing_merged_config(self) -> None:
        defaults = {"CONFIG_VERSION": 2, "SIDEBAR_WIDTH": 270, "VIEW_SIZE": 400}
        user = {"SIDEBAR_WIDTH": 333}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps(user), encoding="utf-8")

            merged = config.merge_config_file(str(path), defaults)

            self.assertEqual(merged, {"CONFIG_VERSION": 2, "SIDEBAR_WIDTH": 333, "VIEW_SIZE": 400})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), merged)
            self.assertEqual(json.loads((Path(str(path) + ".bak")).read_text(encoding="utf-8")), user)


if __name__ == "__main__":
    unittest.main()
