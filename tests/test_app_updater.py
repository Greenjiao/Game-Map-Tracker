import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

import config
import config_defaults
from scripts import updater_main
from scripts import generate_update_manifest, write_default_config
from ui_island.services import app_updater


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class _FakeHttpResponse:
    def __init__(self, status_code: int = 200, payload: dict | None = None, body: bytes = b"") -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self._body = body

    def json(self) -> dict:
        return self._payload

    def iter_content(self, chunk_size: int):
        yield self._body


class _SequenceSession:
    def __init__(self, responses: dict[str, _FakeHttpResponse | Exception]) -> None:
        self.responses = responses
        self.urls: list[str] = []

    def get(self, url: str, *args, **kwargs):
        self.urls.append(url)
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


class AppUpdaterTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_base_dir = config.BASE_DIR
        self._old_config_file = config.CONFIG_FILE
        self._old_localappdata = os.environ.get("LOCALAPPDATA")
        self._old_settings = dict(config.settings)

    def tearDown(self) -> None:
        config.BASE_DIR = self._old_base_dir
        config.CONFIG_FILE = self._old_config_file
        if self._old_localappdata is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = self._old_localappdata
        config.settings.clear()
        config.settings.update(self._old_settings)

    def test_parse_manifest_rejects_unsafe_paths(self) -> None:
        payload = {
            "version": "0.2.0",
            "files": [
                {
                    "path": "../evil.exe",
                    "url": "https://example.test/evil.exe",
                    "sha256": "0" * 64,
                    "size": 1,
                }
            ],
        }

        with self.assertRaises(app_updater.ManifestError):
            app_updater.parse_app_manifest(payload)

    def test_parse_manifest_prompt_update_defaults_to_false(self) -> None:
        payload = {
            "version": "0.2.0",
            "files": [],
        }

        manifest = app_updater.parse_app_manifest(payload)
        result = app_updater.build_update_plan(manifest, current_version="0.1.0")

        self.assertFalse(manifest.prompt_update)
        self.assertFalse(result.prompt_update)
        self.assertFalse(manifest.force_update_prompt)
        self.assertFalse(result.force_update_prompt)

    def test_parse_manifest_prompt_update_flows_to_check_result(self) -> None:
        payload = {
            "version": "0.2.0",
            "prompt_update": True,
            "force_update_prompt": True,
            "files": [],
        }

        manifest = app_updater.parse_app_manifest(payload)
        result = app_updater.build_update_plan(manifest, current_version="0.1.0")

        self.assertTrue(manifest.prompt_update)
        self.assertTrue(result.prompt_update)
        self.assertTrue(manifest.force_update_prompt)
        self.assertTrue(result.force_update_prompt)

    def test_parse_manifest_app_status_defaults_to_normal(self) -> None:
        manifest = app_updater.parse_app_manifest({"version": "0.2.0", "files": []})
        result = app_updater.build_update_plan(manifest, current_version="0.1.0")

        self.assertEqual(manifest.app_status, app_updater.APP_STATUS_NORMAL)
        self.assertEqual(manifest.app_status_message, "")
        self.assertFalse(manifest.app_notice_force_prompt)
        self.assertEqual(result.app_status, app_updater.APP_STATUS_NORMAL)
        self.assertEqual(result.app_status_message, "")
        self.assertFalse(result.app_notice_force_prompt)

    def test_parse_manifest_app_status_flows_to_check_result(self) -> None:
        manifest = app_updater.parse_app_manifest(
            {
                "version": "0.2.0",
                "app_status": "notice",
                "app_notice_force_prompt": True,
                "app_status_message": "公告内容",
                "files": [],
            }
        )
        result = app_updater.build_update_plan(manifest, current_version="0.1.0")

        self.assertEqual(manifest.app_status, app_updater.APP_STATUS_NOTICE)
        self.assertEqual(manifest.app_status_message, "公告内容")
        self.assertTrue(manifest.app_notice_force_prompt)
        self.assertEqual(result.app_status, app_updater.APP_STATUS_NOTICE)
        self.assertEqual(result.app_status_message, "公告内容")
        self.assertTrue(result.app_notice_force_prompt)

    def test_parse_manifest_min_supported_version_defaults_to_disabled(self) -> None:
        manifest = app_updater.parse_app_manifest({"version": "0.2.0", "files": []})
        result = app_updater.build_update_plan(manifest, current_version="0.1.0")

        self.assertEqual(manifest.min_supported_version, "")
        self.assertEqual(manifest.min_supported_version_message, "")
        self.assertFalse(result.requires_min_supported_update)

    def test_parse_manifest_min_supported_version_flows_to_check_result(self) -> None:
        manifest = app_updater.parse_app_manifest(
            {
                "version": "0.2.0",
                "min_supported_version": "0.1.2",
                "min_supported_version_message": "请更新后继续使用",
                "files": [],
            }
        )
        low = app_updater.build_update_plan(manifest, current_version="0.1.1")
        equal = app_updater.build_update_plan(manifest, current_version="0.1.2")
        newer = app_updater.build_update_plan(manifest, current_version="0.1.3")

        self.assertEqual(manifest.min_supported_version, "0.1.2")
        self.assertEqual(manifest.min_supported_version_message, "请更新后继续使用")
        self.assertTrue(low.requires_min_supported_update)
        self.assertEqual(low.min_supported_version, "0.1.2")
        self.assertEqual(low.min_supported_version_message, "请更新后继续使用")
        self.assertFalse(equal.requires_min_supported_update)
        self.assertFalse(newer.requires_min_supported_update)

    def test_parse_manifest_invalid_min_supported_version_is_ignored(self) -> None:
        manifest = app_updater.parse_app_manifest(
            {
                "version": "0.2.0",
                "min_supported_version": "tomorrow",
                "min_supported_version_message": "ignored",
                "files": [],
            }
        )
        result = app_updater.build_update_plan(manifest, current_version="0.1.0")

        self.assertEqual(manifest.min_supported_version, "")
        self.assertEqual(manifest.min_supported_version_message, "")
        self.assertFalse(result.requires_min_supported_update)

    def test_parse_manifest_app_notice_force_prompt_requires_boolean_true(self) -> None:
        manifest = app_updater.parse_app_manifest(
            {
                "version": "0.2.0",
                "app_status": "notice",
                "app_status_message": "notice",
                "app_notice_force_prompt": "false",
                "files": [],
            }
        )

        self.assertFalse(manifest.app_notice_force_prompt)

    def test_parse_manifest_app_status_sanitizes_unknown_and_empty_message(self) -> None:
        unknown = app_updater.parse_app_manifest(
            {
                "version": "0.2.0",
                "app_status": "paused",
                "app_status_message": "ignored",
                "files": [],
            }
        )
        disabled = app_updater.parse_app_manifest(
            {
                "version": "0.2.0",
                "app_status": "disabled",
                "app_status_message": "",
                "files": [],
            }
        )

        self.assertEqual(unknown.app_status, app_updater.APP_STATUS_NORMAL)
        self.assertEqual(unknown.app_status_message, "")
        self.assertEqual(disabled.app_status, app_updater.APP_STATUS_DISABLED)
        self.assertEqual(disabled.app_status_message, app_updater.DEFAULT_APP_STATUS_MESSAGE)

    def test_parse_manifest_preserves_obsolete_config_keys(self) -> None:
        payload = {
            "version": "0.2.0",
            "obsolete_config_keys": [
                "ROUTE_RECENT_LIMIT",
                "ROUTE_RECENT_LIMIT",
                "bad-key",
                "1_BAD",
                "",
                "LEGACY_FLAG",
            ],
            "files": [],
        }

        manifest = app_updater.parse_app_manifest(payload)

        self.assertEqual(manifest.obsolete_config_keys, ("ROUTE_RECENT_LIMIT", "LEGACY_FLAG"))

    def test_normalize_and_compare_versions(self) -> None:
        self.assertEqual(app_updater.normalize_version("v1.2.3"), "1.2.3")
        self.assertEqual(app_updater.normalize_version("1.2.3-beta"), "1.2.3-beta")
        self.assertGreater(app_updater.compare_versions("v1.2.4", "1.2.3"), 0)
        self.assertEqual(app_updater.compare_versions("v1.2.3", "1.2.3"), 0)
        self.assertLess(app_updater.compare_versions("1.2.3-beta", "1.2.3"), 0)

    def test_check_app_update_uses_gitee_first_and_stops_after_success(self) -> None:
        gitee_url = "https://gitee.test/update/app-manifest.json"
        github_url = "https://github.test/update/app-manifest.json"
        session = _SequenceSession(
            {
                gitee_url: _FakeHttpResponse(200, {"version": "0.2.0", "files": []}),
                github_url: _FakeHttpResponse(200, {"version": "0.3.0", "files": []}),
            }
        )

        with patch.object(config, "APP_UPDATE_MANIFEST_URLS", [gitee_url, github_url]), patch.object(
            app_updater, "APP_UPDATE_MANIFEST_URLS", ()
        ):
            result = app_updater.check_app_update(current_version="0.1.0", session=session)

        self.assertTrue(result.ok)
        self.assertEqual(result.latest_version, "0.2.0")
        self.assertEqual(session.urls, [gitee_url])
        self.assertEqual(result.manifest.source_base_url, "https://gitee.test/update/")

    def test_check_app_update_falls_back_to_github_pages(self) -> None:
        gitee_url = "https://gitee.test/update/app-manifest.json"
        github_url = "https://github.test/update/app-manifest.json"
        session = _SequenceSession(
            {
                gitee_url: requests.ConnectionError("offline"),
                github_url: _FakeHttpResponse(200, {"version": "0.2.0", "files": []}),
            }
        )

        with patch.object(config, "APP_UPDATE_MANIFEST_URLS", [gitee_url, github_url]), patch.object(
            app_updater, "APP_UPDATE_MANIFEST_URLS", ()
        ):
            result = app_updater.check_app_update(current_version="0.1.0", session=session)

        self.assertTrue(result.ok)
        self.assertEqual(result.latest_version, "0.2.0")
        self.assertEqual(session.urls, [gitee_url, github_url])
        self.assertEqual(result.manifest.source_base_url, "https://github.test/update/")

    def test_check_app_update_uses_hardcoded_sources_when_config_has_no_sources(self) -> None:
        gitee_url = "https://gitee.com/qingjiao123/Game-Map-Tracker/raw/main/docs/update/app-manifest.json"
        github_url = "https://greenjiao.github.io/Game-Map-Tracker/update/app-manifest.json"
        session = _SequenceSession(
            {
                gitee_url: requests.ConnectionError("offline"),
                github_url: _FakeHttpResponse(200, {"version": "0.2.0", "files": []}),
            }
        )

        with patch.object(config, "APP_UPDATE_MANIFEST_URLS", []), patch.object(
            app_updater, "APP_UPDATE_MANIFEST_URLS", (gitee_url, github_url)
        ):
            result = app_updater.check_app_update(current_version="0.1.0", session=session)

        self.assertTrue(result.ok)
        self.assertEqual(session.urls, [gitee_url, github_url])

    def test_check_app_update_applies_runtime_config_without_writing_config_json(self) -> None:
        manifest_url = "https://gitee.test/update/app-manifest.json"
        session = _SequenceSession(
            {
                manifest_url: _FakeHttpResponse(
                    200,
                    {
                        "version": "0.2.0",
                        "files": [],
                        "runtime_config": {
                            "QUARK_DOWNLOAD_URL": "https://pan.example/download",
                            "ROUTE_RESOURCE_URL": "https://example.test/routes",
                            "ROUTE_RESOURCE_LINKS": [
                                {"name": "Routes", "url": "https://example.test/routes"},
                                {"name": "Backup", "url": "https://example.test/backup"},
                            ],
                            "FEEDBACK_LINKS": [
                                {"name": "Bilibili", "url": "https://space.bilibili.com/example"},
                                {"name": "QQ Group", "url": "https://qm.qq.com/q/example"},
                            ],
                            "APP_ENABLE_VERSIONS": ["GMT-N-0.1.2", "GMT-N-0.1.3", "GMT-N-0.1.3", ""],
                            "APP_UPDATE_MANIFEST_URL": "https://legacy.test/app-manifest.json",
                            "APP_UPDATE_MANIFEST_URLS": [
                                "https://legacy.test/app-manifest.json",
                                "https://github.test/app-manifest.json",
                            ],
                        },
                    },
                ),
            }
        )

        with patch.object(config, "QUARK_DOWNLOAD_URL", ""), patch.object(
            config, "ROUTE_RESOURCE_URL", ""
        ), patch.object(config, "ROUTE_RESOURCE_LINKS", []), patch.object(
            config, "FEEDBACK_LINKS", []
        ), patch.object(config, "APP_UPDATE_MANIFEST_URLS", []), patch.object(
            config, "save_config"
        ) as save_config:
            result = app_updater.check_app_update(
                manifest_url=manifest_url,
                current_version="0.1.0",
                session=session,
            )
            self.assertTrue(result.ok)
            self.assertEqual(config.QUARK_DOWNLOAD_URL, "https://pan.example/download")
            self.assertEqual(config.ROUTE_RESOURCE_URL, "https://example.test/routes")
            self.assertEqual(
                config.ROUTE_RESOURCE_LINKS,
                [
                    {"name": "Routes", "url": "https://example.test/routes"},
                    {"name": "Backup", "url": "https://example.test/backup"},
                ],
            )
            self.assertEqual(
                config.FEEDBACK_LINKS,
                [
                    {"name": "Bilibili", "url": "https://space.bilibili.com/example"},
                    {"name": "QQ Group", "url": "https://qm.qq.com/q/example"},
                ],
            )
            self.assertEqual(config.APP_ENABLE_VERSIONS, ["GMT-N-0.1.2", "GMT-N-0.1.3"])
            self.assertEqual(
                config.APP_UPDATE_MANIFEST_URLS,
                ["https://legacy.test/app-manifest.json", "https://github.test/app-manifest.json"],
            )
            save_config.assert_not_called()

    def test_check_app_update_reports_all_sources_failed(self) -> None:
        gitee_url = "https://gitee.test/update/app-manifest.json"
        github_url = "https://github.test/update/app-manifest.json"
        session = _SequenceSession(
            {
                gitee_url: requests.ConnectionError("offline"),
                github_url: _FakeHttpResponse(500, {}),
            }
        )

        with patch.object(config, "APP_UPDATE_MANIFEST_URLS", [gitee_url, github_url]), patch.object(
            app_updater, "APP_UPDATE_MANIFEST_URLS", ()
        ):
            result = app_updater.check_app_update(current_version="0.1.0", session=session)

        self.assertFalse(result.ok)
        self.assertIn("无法连接所有更新源", result.error)
        self.assertIn("已尝试 2 个更新源", result.error)

    def test_should_show_startup_update_prompt_respects_force_prompt(self) -> None:
        normal = app_updater.AppUpdateCheckResult(
            ok=True,
            current_version="0.1.0",
            latest_version="0.1.0",
            has_update=True,
            prompt_update=True,
        )
        forced = app_updater.AppUpdateCheckResult(
            ok=True,
            current_version="0.1.0",
            latest_version="0.1.0",
            has_update=True,
            force_update_prompt=True,
        )
        no_update = app_updater.AppUpdateCheckResult(
            ok=True,
            current_version="0.1.0",
            latest_version="0.1.0",
            has_update=False,
            force_update_prompt=True,
        )

        self.assertFalse(app_updater.should_show_startup_update_prompt(normal, "0.1.0"))
        self.assertTrue(app_updater.should_show_startup_update_prompt(forced, "0.1.0"))
        self.assertFalse(app_updater.should_show_startup_update_prompt(no_update, "0.1.0"))

    def test_should_show_app_notice_uses_message_ack_key(self) -> None:
        ack_key = app_updater.app_notice_ack_key("  first notice  ")

        self.assertEqual(ack_key, app_updater.app_notice_ack_key("first notice"))
        self.assertFalse(
            app_updater.should_show_app_notice(
                app_updater.APP_STATUS_NOTICE,
                "first notice",
                last_ack_key=ack_key,
            )
        )
        self.assertTrue(
            app_updater.should_show_app_notice(
                app_updater.APP_STATUS_NOTICE,
                "changed notice",
                last_ack_key=ack_key,
            )
        )
        self.assertTrue(
            app_updater.should_show_app_notice(
                app_updater.APP_STATUS_NOTICE,
                "first notice",
                force_prompt=True,
                last_ack_key=ack_key,
            )
        )
        self.assertFalse(
            app_updater.should_show_app_notice(
                app_updater.APP_STATUS_DISABLED,
                "first notice",
                force_prompt=True,
                last_ack_key=ack_key,
            )
        )

    def test_generate_manifest_writes_prompt_update_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Path(root, "demo.txt").write_bytes(b"demo")

            quiet = generate_update_manifest.build_manifest(
                root,
                version="0.2.0",
                base_url="https://example.test/update/",
                notes="",
                requires_launcher_update=False,
                prompt_update=False,
                force_update_prompt=False,
            )
            prompted = generate_update_manifest.build_manifest(
                root,
                version="0.2.0",
                base_url="https://example.test/update/",
                notes="",
                requires_launcher_update=False,
                prompt_update=True,
                force_update_prompt=True,
            )

        self.assertFalse(quiet["prompt_update"])
        self.assertFalse(quiet["force_update_prompt"])
        self.assertTrue(prompted["prompt_update"])
        self.assertTrue(prompted["force_update_prompt"])

    def test_generate_manifest_writes_app_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Path(root, "demo.txt").write_bytes(b"demo")

            manifest = generate_update_manifest.build_manifest(
                root,
                version="0.2.0",
                base_url="https://example.test/update/",
                notes="",
                requires_launcher_update=False,
                prompt_update=False,
                force_update_prompt=False,
                app_status="disabled",
                app_status_message="停止使用说明",
            )
            notice = generate_update_manifest.build_manifest(
                root,
                version="0.2.0",
                base_url="https://example.test/update/",
                notes="",
                requires_launcher_update=False,
                prompt_update=False,
                force_update_prompt=False,
                app_status="notice",
                app_status_message="notice",
                app_notice_force_prompt=True,
            )
            unknown = generate_update_manifest.build_manifest(
                root,
                version="0.2.0",
                base_url="https://example.test/update/",
                notes="",
                requires_launcher_update=False,
                prompt_update=False,
                force_update_prompt=False,
                app_status="paused",
                app_status_message="ignored",
            )

        self.assertEqual(manifest["app_status"], "disabled")
        self.assertEqual(manifest["app_status_message"], "停止使用说明")
        self.assertFalse(manifest["app_notice_force_prompt"])
        self.assertTrue(notice["app_notice_force_prompt"])
        self.assertEqual(unknown["app_status"], "normal")
        self.assertEqual(unknown["app_status_message"], "")
        self.assertFalse(unknown["app_notice_force_prompt"])

    def test_generate_manifest_writes_min_supported_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Path(root, "demo.txt").write_bytes(b"demo")

            manifest = generate_update_manifest.build_manifest(
                root,
                version="0.2.0",
                base_url="https://example.test/update/",
                notes="",
                requires_launcher_update=False,
                prompt_update=False,
                force_update_prompt=False,
                min_supported_version="0.1.2",
                min_supported_version_message="请更新后继续使用",
            )
            default_message = generate_update_manifest.build_manifest(
                root,
                version="0.2.0",
                base_url="https://example.test/update/",
                notes="",
                requires_launcher_update=False,
                prompt_update=False,
                force_update_prompt=False,
                min_supported_version="0.1.2",
            )

        self.assertEqual(manifest["min_supported_version"], "0.1.2")
        self.assertEqual(manifest["min_supported_version_message"], "请更新后继续使用")
        self.assertEqual(
            default_message["min_supported_version_message"],
            generate_update_manifest.DEFAULT_MIN_SUPPORTED_VERSION_MESSAGE,
        )

    def test_generate_manifest_rejects_min_supported_version_above_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Path(root, "demo.txt").write_bytes(b"demo")

            with self.assertRaises(ValueError):
                generate_update_manifest.build_manifest(
                    root,
                    version="0.2.0",
                    base_url="https://example.test/update/",
                    notes="",
                    requires_launcher_update=False,
                    prompt_update=False,
                    force_update_prompt=False,
                    min_supported_version="0.2.1",
                )

    def test_generate_manifest_writes_obsolete_config_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Path(root, "demo.txt").write_bytes(b"demo")

            manifest = generate_update_manifest.build_manifest(
                root,
                version="0.2.0",
                base_url="https://example.test/update/",
                notes="",
                requires_launcher_update=False,
                prompt_update=False,
                force_update_prompt=False,
                obsolete_config_keys=[
                    "ROUTE_RECENT_LIMIT",
                    "ROUTE_RECENT_LIMIT",
                    "bad-key",
                    "1_BAD",
                    "LEGACY_FLAG",
                ],
            )

        self.assertEqual(manifest["obsolete_config_keys"], ["ROUTE_RECENT_LIMIT", "LEGACY_FLAG"])

    def test_generate_manifest_protects_user_map_files_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Path(root, "demo.txt").write_bytes(b"demo")
            Path(root, "big_map.png").write_bytes(b"legacy-map")
            Path(root, "big_map_17173.png").write_bytes(b"other-map")
            maps_dir = Path(root, "maps")
            maps_dir.mkdir()
            Path(maps_dir, "README.md").write_text("maps go here", encoding="utf-8")
            Path(maps_dir, "custom.png").write_bytes(b"user-map")
            bundled_map_dir = maps_dir / "卡洛西亚大陆"
            bundled_map_dir.mkdir()
            (bundled_map_dir / "big_map_17173.png").write_bytes(b"legacy-bundled-map")
            (bundled_map_dir / "big_map_17173带传送图标.png").write_bytes(b"legacy-bundled-map-with-icons")

            manifest = generate_update_manifest.build_manifest(
                root,
                version="0.2.0",
                base_url="https://example.test/update/",
                notes="",
                requires_launcher_update=False,
                prompt_update=False,
                force_update_prompt=False,
            )

        paths = {item["path"] for item in manifest["files"]}
        self.assertIn("demo.txt", paths)
        self.assertNotIn("big_map.png", paths)
        self.assertNotIn("big_map_17173.png", paths)
        self.assertNotIn("maps/README.md", paths)
        self.assertNotIn("maps/custom.png", paths)
        self.assertNotIn("maps/卡洛西亚大陆/big_map_17173.png", paths)
        self.assertNotIn("maps/卡洛西亚大陆/big_map_17173带传送图标.png", paths)
        self.assertEqual(manifest["delete"], list(generate_update_manifest.DEFAULT_DELETE_PATHS))

    def test_generate_manifest_can_force_delete_legacy_root_big_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Path(root, "demo.txt").write_bytes(b"demo")

            manifest = generate_update_manifest.build_manifest(
                root,
                version="0.2.0",
                base_url="https://example.test/update/",
                notes="",
                requires_launcher_update=False,
                prompt_update=False,
                force_update_prompt=False,
                delete_paths=["big_map.png"],
            )

        paths = {item["path"] for item in manifest["files"]}
        self.assertIn("demo.txt", paths)
        self.assertNotIn("big_map.png", paths)
        self.assertEqual(manifest["delete"], list(generate_update_manifest.DEFAULT_DELETE_PATHS))

    def test_generate_manifest_can_explicitly_include_protected_map_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = Path(root, "maps", "custom.png")
            target.parent.mkdir()
            target.write_bytes(b"publish-once")

            manifest = generate_update_manifest.build_manifest(
                root,
                version="0.2.0",
                base_url="https://example.test/update/",
                notes="",
                requires_launcher_update=False,
                prompt_update=False,
                force_update_prompt=False,
                include_paths=["maps/custom.png"],
            )

        self.assertEqual([item["path"] for item in manifest["files"]], ["maps/custom.png"])

    def test_generate_manifest_includes_new_bundled_map_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            map_dir = Path(root, "maps", "卡洛西亚大陆")
            map_dir.mkdir(parents=True)
            (map_dir / "big_map_17173.png").write_bytes(b"map")
            (map_dir / "big_map_17173带传送图标.png").write_bytes(b"map-with-icons")
            (map_dir / "big_map_17173带传送点图标.png").write_bytes(b"map-with-teleport-icons")
            (map_dir / "big_map_new.png").write_bytes(b"new-map")
            Path(root, "maps", "custom.png").write_bytes(b"user-map")

            manifest = generate_update_manifest.build_manifest(
                root,
                version="0.2.0",
                base_url="https://example.test/update/",
                notes="",
                requires_launcher_update=False,
                prompt_update=False,
                force_update_prompt=False,
            )

        paths = [item["path"] for item in manifest["files"]]
        self.assertEqual(
            paths,
            [
                "maps/卡洛西亚大陆/big_map_new.png",
            ],
        )
        self.assertEqual(manifest["delete"], list(generate_update_manifest.DEFAULT_DELETE_PATHS))

    def test_write_default_config_uses_clean_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp, "config.json")
            write_default_config.write_default_config(target)
            payload = json.loads(target.read_text(encoding="utf-8"))

        self.assertEqual(payload, config_defaults.DEFAULT_CONFIG)
        self.assertEqual(payload["MINIMAP"], {})
        self.assertEqual(payload["APP_UPDATE_LAST_PROMPTED_VERSION"], "")
        self.assertEqual(payload["APP_NOTICE_LAST_ACK_KEY"], "")

    def test_generate_manifest_writes_runtime_config_from_explicit_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Path(root, "demo.txt").write_bytes(b"demo")
            runtime_config_path = root / "private-runtime-config.json"
            runtime_config_path.write_text(
                json.dumps(
                    {
                        "QUARK_DOWNLOAD_URL": " https://pan.example/download ",
                        "ROUTE_RESOURCE_URL": "https://example.test/routes",
                        "ROUTE_RESOURCE_LINKS": [
                            {"name": " Routes ", "url": " https://example.test/routes "},
                            {"name": "Routes", "url": "https://example.test/routes"},
                            {"name": "Backup", "url": "https://example.test/backup"},
                            {"name": "", "url": "https://example.test/empty-name"},
                            {"name": "Missing URL"},
                            "https://wrong.example/routes",
                        ],
                        "FEEDBACK_LINKS": [
                            {"name": " Bilibili ", "url": " https://space.bilibili.com/example "},
                            {"name": "Bilibili", "url": "https://space.bilibili.com/example"},
                            {"name": "QQ Group", "url": "https://qm.qq.com/q/example"},
                            {"name": "", "url": "https://wrong.example/empty-name"},
                            {"name": "Missing URL"},
                        ],
                        "APP_UPDATE_MANIFEST_URL": "https://gitee.test/app-manifest.json",
                        "APP_UPDATE_MANIFEST_URLS": [
                            "https://gitee.test/app-manifest.json",
                            "https://gitee.test/app-manifest.json",
                            "https://github.test/app-manifest.json",
                            "",
                        ],
                        "APP_ENABLE_VERSIONS": ["0.1.2", "0.1.3", "0.1.3", ""],
                        "SECRET_TOKEN": "do-not-ship",
                        "ROUTE_DEFAULT_COLOR": "#ff00ff",
                    }
                ),
                encoding="utf-8",
            )

            manifest = generate_update_manifest.build_manifest(
                root,
                version="0.2.0",
                base_url="https://example.test/update/",
                notes="",
                requires_launcher_update=False,
                prompt_update=False,
                force_update_prompt=False,
                runtime_config_path=runtime_config_path,
            )

        self.assertEqual(
            manifest["runtime_config"],
            {
                "QUARK_DOWNLOAD_URL": "https://pan.example/download",
                "ROUTE_RESOURCE_URL": "https://example.test/routes",
                "ROUTE_RESOURCE_LINKS": [
                    {"name": "Routes", "url": "https://example.test/routes"},
                    {"name": "Backup", "url": "https://example.test/backup"},
                ],
                "FEEDBACK_LINKS": [
                    {"name": "Bilibili", "url": "https://space.bilibili.com/example"},
                    {"name": "QQ Group", "url": "https://qm.qq.com/q/example"},
                ],
                "APP_UPDATE_MANIFEST_URLS": [
                    "https://gitee.test/app-manifest.json",
                    "https://github.test/app-manifest.json",
                ],
                "APP_ENABLE_VERSIONS": ["0.1.2", "0.1.3"],
            },
        )
        self.assertNotIn("SECRET_TOKEN", manifest["runtime_config"])
        self.assertNotIn("ROUTE_DEFAULT_COLOR", manifest["runtime_config"])

    def test_generate_manifest_ignores_missing_and_invalid_runtime_config_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Path(root, "demo.txt").write_bytes(b"demo")

            missing_manifest = generate_update_manifest.build_manifest(
                root,
                version="0.2.0",
                base_url="https://example.test/update/",
                notes="",
                requires_launcher_update=False,
                prompt_update=False,
                force_update_prompt=False,
                runtime_config_path=root / "missing-runtime-config.json",
            )

            runtime_config_path = root / "runtime-config.json"
            runtime_config_path.write_text(
                json.dumps(
                    {
                        "QUARK_DOWNLOAD_URL": ["https://wrong.example"],
                        "ROUTE_RESOURCE_URL": 123,
                        "ROUTE_RESOURCE_LINKS": [
                            {"name": "", "url": "https://wrong.example/routes"},
                            {"name": "Missing URL"},
                            "https://wrong.example/routes",
                        ],
                        "FEEDBACK_LINKS": [
                            {"name": "", "url": "https://wrong.example/feedback"},
                            {"name": "Missing URL"},
                            "https://wrong.example/feedback",
                        ],
                        "APP_UPDATE_MANIFEST_URL": False,
                        "APP_UPDATE_MANIFEST_URLS": "https://wrong.example",
                    }
                ),
                encoding="utf-8",
            )
            invalid_manifest = generate_update_manifest.build_manifest(
                root,
                version="0.2.0",
                base_url="https://example.test/update/",
                notes="",
                requires_launcher_update=False,
                prompt_update=False,
                force_update_prompt=False,
                runtime_config_path=runtime_config_path,
            )
            runtime_config_path.write_text("{broken", encoding="utf-8")
            broken_manifest = generate_update_manifest.build_manifest(
                root,
                version="0.2.0",
                base_url="https://example.test/update/",
                notes="",
                requires_launcher_update=False,
                prompt_update=False,
                force_update_prompt=False,
                runtime_config_path=runtime_config_path,
            )

        self.assertNotIn("runtime_config", missing_manifest)
        self.assertNotIn("runtime_config", invalid_manifest)
        self.assertNotIn("runtime_config", broken_manifest)

    def test_generate_manifest_excludes_user_routes_and_points(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Path(root, "demo.txt").write_bytes(b"demo")
            route = Path(root, "routes", "地区路线", "雪山__来自用户道临沂.json")
            route.parent.mkdir(parents=True)
            route.write_text("{}", encoding="utf-8")
            recent_routes = Path(root, "routes", "recent_routes.json")
            recent_routes.write_text("[]", encoding="utf-8")
            points = Path(root, "tools", "points_all", "points.json")
            points.parent.mkdir(parents=True)
            points.write_text("{}", encoding="utf-8")
            converter = Path(root, "tools", "json_txt_converter.exe")
            converter.write_bytes(b"converter")
            cache = Path(root, "tools", "points_get", ".cache_17173_locations.json")
            cache.parent.mkdir(parents=True)
            cache.write_text("{}", encoding="utf-8")
            icon = Path(root, "tools", "points_icon", "icons.json")
            icon.parent.mkdir(parents=True)
            icon.write_text("{}", encoding="utf-8")
            annotation = Path(root, "annotations", "points.json")
            annotation.parent.mkdir(parents=True)
            annotation.write_text("{}", encoding="utf-8")
            user_map = Path(root, "maps", "custom.png")
            user_map.parent.mkdir(parents=True)
            user_map.write_bytes(b"map")

            manifest = generate_update_manifest.build_manifest(
                root,
                version="0.2.0",
                base_url="https://example.test/update/",
                notes="",
                requires_launcher_update=False,
                prompt_update=False,
                force_update_prompt=False,
            )

        paths = {item["path"] for item in manifest["files"]}
        self.assertIn("demo.txt", paths)
        self.assertNotIn("tools/json_txt_converter.exe", paths)
        self.assertNotIn("routes/地区路线/雪山__来自用户道临沂.json", paths)
        self.assertNotIn("routes/recent_routes.json", paths)
        self.assertNotIn("tools/points_all/points.json", paths)
        self.assertNotIn("tools/points_get/.cache_17173_locations.json", paths)
        self.assertNotIn("tools/points_icon/icons.json", paths)
        self.assertNotIn("annotations/points.json", paths)
        self.assertNotIn("maps/custom.png", paths)

    def test_manifest_generator_excludes_protected_publish_paths(self) -> None:
        self.assertTrue(generate_update_manifest.is_user_data_path("tools/json_txt_converter.exe"))
        self.assertTrue(generate_update_manifest.is_user_data_path("tools/points_all/points.json"))
        self.assertTrue(generate_update_manifest.is_user_data_path("tools/points_get/.cache_17173_locations.json"))
        self.assertTrue(generate_update_manifest.is_user_data_path("tools/points_icon/icons.json"))
        self.assertTrue(generate_update_manifest.is_user_data_path("routes/demo.json"))
        self.assertTrue(generate_update_manifest.is_user_data_path("annotations/points.json"))
        self.assertTrue(generate_update_manifest.is_user_data_path("maps/custom.png"))

    def test_parse_manifest_respects_listed_routes_and_points(self) -> None:
        payload = {
            "version": "0.2.0",
            "files": [
                {
                    "path": "routes/地区路线/雪山__来自用户道临沂.json",
                    "url": "https://example.test/route.json",
                    "sha256": "0" * 64,
                    "size": 1,
                },
                {
                    "path": "tools/points_all/points.json",
                    "url": "https://example.test/points.json",
                    "sha256": "1" * 64,
                    "size": 1,
                },
                {
                    "path": "routes/recent_routes.json",
                    "url": "https://example.test/recent_routes.json",
                    "sha256": "5" * 64,
                    "size": 1,
                },
                {
                    "path": "tools/points_get/.cache_17173_locations.json",
                    "url": "https://example.test/cache.json",
                    "sha256": "3" * 64,
                    "size": 1,
                },
                {
                    "path": "tools/points_icon/icons.json",
                    "url": "https://example.test/icons.json",
                    "sha256": "4" * 64,
                    "size": 1,
                },
                {
                    "path": "tools/json_txt_converter.exe",
                    "url": "https://example.test/json_txt_converter.exe",
                    "sha256": "6" * 64,
                    "size": 1,
                },
                {
                    "path": "demo.txt",
                    "url": "https://example.test/demo.txt",
                    "sha256": "2" * 64,
                    "size": 1,
                },
            ],
            "delete": [
                "routes/demo.json",
                "routes/recent_routes.json",
                "tools/points_all/points.json",
                "tools/points_get/.cache_17173_locations.json",
                "tools/points_icon/icons.json",
                "config.json",
                "demo-old.txt",
            ],
        }

        manifest = app_updater.parse_app_manifest(payload)

        self.assertEqual(
            [file.path for file in manifest.files],
            [str(item["path"]) for item in payload["files"]],
        )
        self.assertEqual(
            manifest.delete,
            (
                "routes/demo.json",
                "routes/recent_routes.json",
                "tools/points_all/points.json",
                "tools/points_get/.cache_17173_locations.json",
                "tools/points_icon/icons.json",
                "config.json",
                "demo-old.txt",
            ),
        )

    def test_download_changed_files_reports_progress(self) -> None:
        payload = b"abcdef"
        manifest = app_updater.parse_app_manifest(
            {
                "version": "0.2.0",
                "files": [
                    {
                        "path": "demo.bin",
                        "url": "https://example.test/demo.bin",
                        "sha256": _sha256_bytes(payload),
                        "size": len(payload),
                    }
                ],
            }
        )

        class FakeResponse:
            status_code = 200

            def iter_content(self, chunk_size: int):
                yield b"abc"
                yield b"def"

        class FakeSession:
            def get(self, *args, **kwargs):
                return FakeResponse()

        with tempfile.TemporaryDirectory() as tmp:
            config.BASE_DIR = tmp
            staging = Path(tmp, "staging")
            plan = app_updater.build_update_plan(manifest, current_version="0.1.0")
            events: list[tuple[int, int, str]] = []

            with patch("ui_island.services.app_updater.tempfile.mkdtemp", return_value=str(staging)):
                result_path = app_updater.download_changed_files(
                    plan,
                    session=FakeSession(),
                    progress_callback=lambda downloaded, total, path: events.append((downloaded, total, path)),
                )

            self.assertEqual(Path(result_path, "demo.bin").read_bytes(), payload)
            self.assertEqual(events[0], (0, len(payload), "demo.bin"))
            self.assertIn((len(payload), len(payload), "demo.bin"), events)
            self.assertEqual(events[-1], (len(payload), len(payload), ""))

    def test_download_changed_files_prefers_manifest_source_base_url(self) -> None:
        payload = b"from gitee"
        manifest = app_updater.parse_app_manifest(
            {
                "version": "0.2.0",
                "files": [
                    {
                        "path": "dir/demo.bin",
                        "url": "https://github.test/update/dir/demo.bin",
                        "sha256": _sha256_bytes(payload),
                        "size": len(payload),
                    }
                ],
            },
            source_base_url="https://gitee.test/update/",
        )
        session = _SequenceSession({"https://gitee.test/update/dir/demo.bin": _FakeHttpResponse(200, body=payload)})

        with tempfile.TemporaryDirectory() as tmp:
            config.BASE_DIR = tmp
            staging = Path(tmp, "staging")
            plan = app_updater.build_update_plan(manifest, current_version="0.1.0")
            with patch("ui_island.services.app_updater.tempfile.mkdtemp", return_value=str(staging)):
                app_updater.download_changed_files(plan, session=session)

        self.assertEqual(session.urls, ["https://gitee.test/update/dir/demo.bin"])

    def test_download_changed_files_falls_back_to_manifest_file_url(self) -> None:
        payload = b"from github"
        manifest = app_updater.parse_app_manifest(
            {
                "version": "0.2.0",
                "files": [
                    {
                        "path": "demo.bin",
                        "url": "https://github.test/update/demo.bin",
                        "sha256": _sha256_bytes(payload),
                        "size": len(payload),
                    }
                ],
            },
            source_base_url="https://gitee.test/update/",
        )
        session = _SequenceSession(
            {
                "https://gitee.test/update/demo.bin": _FakeHttpResponse(500),
                "https://github.test/update/demo.bin": _FakeHttpResponse(200, body=payload),
            }
        )

        with tempfile.TemporaryDirectory() as tmp:
            config.BASE_DIR = tmp
            staging = Path(tmp, "staging")
            plan = app_updater.build_update_plan(manifest, current_version="0.1.0")
            with patch("ui_island.services.app_updater.tempfile.mkdtemp", return_value=str(staging)):
                result_path = app_updater.download_changed_files(plan, session=session)
            self.assertEqual(Path(result_path, "demo.bin").read_bytes(), payload)

        self.assertEqual(
            session.urls,
            ["https://gitee.test/update/demo.bin", "https://github.test/update/demo.bin"],
        )

    def test_update_error_hint_is_not_duplicated(self) -> None:
        once = app_updater.strings.with_update_error_hint("下载失败")
        twice = app_updater.strings.with_update_error_hint(once)

        self.assertEqual(once, twice)
        self.assertIn("长期更新失败", once)

    def test_build_update_plan_detects_restart_file(self) -> None:
        exe_payload = b"new exe"
        manifest = app_updater.parse_app_manifest(
            {
                "version": "0.2.0",
                "files": [
                    {
                        "path": "GMT-N.exe",
                        "url": "https://example.test/GMT-N.exe",
                        "sha256": _sha256_bytes(exe_payload),
                        "size": len(exe_payload),
                    }
                ],
            }
        )

        with tempfile.TemporaryDirectory() as tmp:
            config.BASE_DIR = tmp
            Path(tmp, "GMT-N.exe").write_bytes(b"old exe")

            result = app_updater.build_update_plan(manifest, current_version="0.1.0")

        self.assertTrue(result.ok)
        self.assertTrue(result.has_update)
        self.assertTrue(result.requires_restart)
        self.assertEqual(result.changed_files[0].file.path, "GMT-N.exe")

    def test_build_update_plan_blocks_older_manifest_file_overwrite(self) -> None:
        exe_payload = b"older remote exe"
        manifest = app_updater.parse_app_manifest(
            {
                "version": "0.1.2",
                "prompt_update": True,
                "force_update_prompt": True,
                "requires_launcher_update": True,
                "files": [
                    {
                        "path": "GMT-N.exe",
                        "url": "https://example.test/GMT-N.exe",
                        "sha256": _sha256_bytes(exe_payload),
                        "size": len(exe_payload),
                    }
                ],
                "delete": ["old.txt"],
            }
        )

        with tempfile.TemporaryDirectory() as tmp:
            config.BASE_DIR = tmp
            Path(tmp, "GMT-N.exe").write_bytes(b"newer local exe")
            Path(tmp, "old.txt").write_text("keep", encoding="utf-8")

            result = app_updater.build_update_plan(manifest, current_version="0.1.3")

        self.assertTrue(result.ok)
        self.assertFalse(result.has_update)
        self.assertFalse(result.requires_restart)
        self.assertFalse(result.prompt_update)
        self.assertFalse(result.force_update_prompt)
        self.assertEqual(result.changed_files, ())
        self.assertEqual(result.delete_files, ())
        self.assertEqual(result.download_size, 0)

    def test_build_update_plan_allows_newer_program_update_from_012(self) -> None:
        exe_payload = b"new exe"
        manifest = app_updater.parse_app_manifest(
            {
                "version": "0.1.3",
                "files": [
                    {
                        "path": "GMT-N.exe",
                        "url": "https://example.test/GMT-N.exe",
                        "sha256": _sha256_bytes(exe_payload),
                        "size": len(exe_payload),
                    }
                ],
            }
        )

        with tempfile.TemporaryDirectory() as tmp:
            config.BASE_DIR = tmp
            Path(tmp, "GMT-N.exe").write_bytes(b"old exe")

            result = app_updater.build_update_plan(manifest, current_version="0.1.2")

        self.assertTrue(result.ok)
        self.assertTrue(result.has_update)
        self.assertTrue(result.requires_restart)
        self.assertEqual([change.file.path for change in result.changed_files], ["GMT-N.exe"])

    def test_build_update_plan_respects_manifest_route_files_and_preserves_local_conflict(self) -> None:
        old_payload = b"old route"
        new_payload = b"new route"
        manifest = app_updater.AppUpdateManifest(
            version="0.2.0",
            notes="",
            files=(
                app_updater.ManifestFile(
                    path="routes/demo.json",
                    url="https://example.test/routes/demo.json",
                    sha256=_sha256_bytes(new_payload),
                    size=len(new_payload),
                ),
            ),
            delete=("routes/old.json",),
        )
        installed = {"files": {"routes/demo.json": {"sha256": _sha256_bytes(old_payload)}}}

        with tempfile.TemporaryDirectory() as tmp:
            config.BASE_DIR = tmp
            route = Path(tmp, "routes", "demo.json")
            route.parent.mkdir(parents=True)
            route.write_bytes(b"user edited")

            result = app_updater.build_update_plan(
                manifest,
                current_version="0.1.0",
                installed_manifest=installed,
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.changed_files, ())
        self.assertEqual(result.delete_files, ())
        self.assertEqual(result.skipped_conflicts, ("routes/demo.json",))

    def test_build_update_plan_delete_forces_user_data_even_when_locally_modified(self) -> None:
        manifest = app_updater.AppUpdateManifest(
            version="0.2.0",
            notes="",
            files=(),
            delete=("routes/bad.json", "annotations/bad-pack"),
        )
        installed = {"files": {"routes/bad.json": {"sha256": _sha256_bytes(b"original")}}}

        with tempfile.TemporaryDirectory() as tmp:
            config.BASE_DIR = tmp
            route = Path(tmp, "routes", "bad.json")
            route.parent.mkdir(parents=True)
            route.write_bytes(b"user edited")
            directory = Path(tmp, "annotations", "bad-pack")
            directory.mkdir(parents=True)
            Path(directory, "points.json").write_text("{}", encoding="utf-8")

            result = app_updater.build_update_plan(
                manifest,
                current_version="0.1.0",
                installed_manifest=installed,
            )

        self.assertEqual(result.delete_files, ("routes/bad.json", "annotations/bad-pack"))
        self.assertEqual(result.skipped_conflicts, ())

    def test_build_update_plan_allows_json_txt_converter_when_manifest_lists_it(self) -> None:
        payload = b"converter"
        manifest = app_updater.parse_app_manifest(
            {
                "version": "0.2.0",
                "files": [
                    {
                        "path": "tools/json_txt_converter.exe",
                        "url": "https://example.test/tools/json_txt_converter.exe",
                        "sha256": _sha256_bytes(payload),
                        "size": len(payload),
                    }
                ],
            }
        )

        with tempfile.TemporaryDirectory() as tmp:
            config.BASE_DIR = tmp
            result = app_updater.build_update_plan(
                manifest,
                current_version="0.2.0",
                installed_manifest={},
        )

        self.assertTrue(result.ok)
        self.assertTrue(result.has_update)
        self.assertEqual([change.file.path for change in result.changed_files], ["tools/json_txt_converter.exe"])

    def test_install_config_update_merges_without_overwriting_user_values(self) -> None:
        defaults = {
            "CONFIG_VERSION": 3,
            "SIDEBAR_WIDTH": 270,
            "VIEW_SIZE": 500,
            "WINDOW_GEOMETRY": {"x": 0, "y": 0, "width": 420, "height": 360},
        }
        defaults_bytes = json.dumps(defaults, ensure_ascii=False).encode("utf-8")
        manifest = app_updater.parse_app_manifest(
            {
                "version": "0.2.0",
                "obsolete_config_keys": ["OLD_ROUTE_LIMIT"],
                "files": [
                    {
                        "path": "config.json",
                        "url": "https://example.test/config.json",
                        "sha256": _sha256_bytes(defaults_bytes),
                        "size": len(defaults_bytes),
                        "install": "merge_config",
                    }
                ],
            }
        )
        plan = app_updater.build_update_plan(manifest, current_version="0.1.0", installed_manifest={})

        with tempfile.TemporaryDirectory() as tmp:
            config.BASE_DIR = tmp
            config.CONFIG_FILE = str(Path(tmp, "config.json"))
            Path(config.CONFIG_FILE).write_text(
                json.dumps(
                    {
                        "SIDEBAR_WIDTH": 333,
                        "WINDOW_GEOMETRY": {"x": 9, "y": 8},
                        "OLD_ROUTE_LIMIT": 3,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            staging = Path(tmp, "staging")
            staging.mkdir()
            Path(staging, "config.json").write_text(json.dumps(defaults, ensure_ascii=False), encoding="utf-8")

            result = app_updater.install_non_restart_update(plan, staging)
            merged = json.loads(Path(config.CONFIG_FILE).read_text(encoding="utf-8"))

        self.assertTrue(result.ok)
        self.assertEqual(merged["CONFIG_VERSION"], 3)
        self.assertEqual(merged["SIDEBAR_WIDTH"], 333)
        self.assertEqual(merged["VIEW_SIZE"], 500)
        self.assertEqual(merged["WINDOW_GEOMETRY"], {"x": 9, "y": 8, "width": 420, "height": 360})
        self.assertNotIn("OLD_ROUTE_LIMIT", merged)

    def test_install_update_can_force_delete_legacy_root_big_map(self) -> None:
        manifest = app_updater.AppUpdateManifest(
            version="0.2.0",
            notes="",
            files=(),
            delete=("big_map.png",),
        )

        with tempfile.TemporaryDirectory() as tmp:
            config.BASE_DIR = tmp
            target = Path(tmp, "big_map.png")
            target.write_bytes(b"legacy")
            staging = Path(tmp, "staging")
            staging.mkdir()
            plan = app_updater.build_update_plan(manifest, current_version="0.1.0")

            result = app_updater.install_non_restart_update(plan, staging)

            self.assertTrue(result.ok)
            self.assertFalse(target.exists())
            self.assertEqual(result.installed_files, ("big_map.png",))

    def test_config_local_change_does_not_trigger_update_when_defaults_installed(self) -> None:
        defaults = {"CONFIG_VERSION": 2, "SIDEBAR_WIDTH": 270}
        defaults_bytes = json.dumps(defaults, ensure_ascii=False).encode("utf-8")
        manifest = app_updater.parse_app_manifest(
            {
                "version": "0.2.0",
                "files": [
                    {
                        "path": "config.json",
                        "url": "https://example.test/config.json",
                        "sha256": _sha256_bytes(defaults_bytes),
                        "size": len(defaults_bytes),
                        "install": "merge_config",
                    }
                ],
            }
        )
        installed = {"files": {"config.json": {"sha256": _sha256_bytes(defaults_bytes)}}}

        with tempfile.TemporaryDirectory() as tmp:
            config.BASE_DIR = tmp
            Path(tmp, "config.json").write_text(
                json.dumps({"CONFIG_VERSION": 2, "SIDEBAR_WIDTH": 333}, ensure_ascii=False),
                encoding="utf-8",
            )

            result = app_updater.build_update_plan(
                manifest,
                current_version="0.2.0",
                installed_manifest=installed,
            )

        self.assertTrue(result.ok)
        self.assertFalse(result.has_update)
        self.assertEqual(result.changed_files, ())

    def test_config_local_change_is_ignored_without_installed_manifest_on_same_version(self) -> None:
        defaults = {"CONFIG_VERSION": 2, "SIDEBAR_WIDTH": 270}
        defaults_bytes = json.dumps(defaults, ensure_ascii=False).encode("utf-8")
        manifest = app_updater.parse_app_manifest(
            {
                "version": "0.2.0",
                "files": [
                    {
                        "path": "config.json",
                        "url": "https://example.test/config.json",
                        "sha256": _sha256_bytes(defaults_bytes),
                        "size": len(defaults_bytes),
                        "install": "merge_config",
                    }
                ],
            }
        )

        with tempfile.TemporaryDirectory() as tmp:
            config.BASE_DIR = tmp
            Path(tmp, "config.json").write_text(
                json.dumps({"CONFIG_VERSION": 2, "SIDEBAR_WIDTH": 333}, ensure_ascii=False),
                encoding="utf-8",
            )

            result = app_updater.build_update_plan(
                manifest,
                current_version="0.2.0",
                installed_manifest={},
            )

        self.assertTrue(result.ok)
        self.assertFalse(result.has_update)
        self.assertEqual(result.changed_files, ())

    def test_config_defaults_update_runs_without_installed_manifest_when_version_is_newer(self) -> None:
        defaults = {"CONFIG_VERSION": 3, "SIDEBAR_WIDTH": 270, "VIEW_SIZE": 600}
        defaults_bytes = json.dumps(defaults, ensure_ascii=False).encode("utf-8")
        manifest = app_updater.parse_app_manifest(
            {
                "version": "0.3.0",
                "files": [
                    {
                        "path": "config.json",
                        "url": "https://example.test/config.json",
                        "sha256": _sha256_bytes(defaults_bytes),
                        "size": len(defaults_bytes),
                        "install": "merge_config",
                    }
                ],
            }
        )

        with tempfile.TemporaryDirectory() as tmp:
            config.BASE_DIR = tmp
            Path(tmp, "config.json").write_text(
                json.dumps({"CONFIG_VERSION": 2, "SIDEBAR_WIDTH": 333}, ensure_ascii=False),
                encoding="utf-8",
            )

            result = app_updater.build_update_plan(
                manifest,
                current_version="0.2.0",
                installed_manifest={},
            )

        self.assertTrue(result.ok)
        self.assertTrue(result.has_update)
        self.assertEqual(result.changed_files[0].file.path, "config.json")

    def test_write_restart_update_job_contains_changed_files_and_manifest(self) -> None:
        payload = b"new exe"
        manifest = app_updater.parse_app_manifest(
            {
                "version": "0.2.0",
                "obsolete_config_keys": ["ROUTE_RECENT_LIMIT"],
                "files": [
                    {
                        "path": "GMT-N.exe",
                        "url": "https://example.test/GMT-N.exe",
                        "sha256": _sha256_bytes(payload),
                        "size": len(payload),
                    }
                ],
            }
        )

        with tempfile.TemporaryDirectory() as tmp:
            config.BASE_DIR = tmp
            Path(tmp, "GMT-N.exe").write_bytes(b"old exe")
            staging = Path(tmp, "staging")
            staging.mkdir()
            plan = app_updater.build_update_plan(manifest, current_version="0.1.0")

            job_path = app_updater.write_restart_update_job(plan, staging)
            job = json.loads(job_path.read_text(encoding="utf-8"))

        self.assertEqual(job["version"], "0.2.0")
        self.assertEqual(job["files"][0]["path"], "GMT-N.exe")
        self.assertEqual(job["manifest"]["files"][0]["sha256"], _sha256_bytes(payload))
        self.assertEqual(job["delete"], [])
        self.assertEqual(job["obsolete_config_keys"], ["ROUTE_RECENT_LIMIT"])

    def test_start_restart_update_reports_missing_updater(self) -> None:
        payload = b"new exe"
        manifest = app_updater.parse_app_manifest(
            {
                "version": "0.2.0",
                "files": [
                    {
                        "path": "GMT-N.exe",
                        "url": "https://example.test/GMT-N.exe",
                        "sha256": _sha256_bytes(payload),
                        "size": len(payload),
                    }
                ],
            }
        )

        with tempfile.TemporaryDirectory() as tmp:
            config.BASE_DIR = tmp
            Path(tmp, "GMT-N.exe").write_bytes(b"old exe")
            staging = Path(tmp, "staging")
            staging.mkdir()
            plan = app_updater.build_update_plan(manifest, current_version="0.1.0")

            result = app_updater.start_restart_update(plan, staging, parent_pid=0)

        self.assertFalse(result.ok)
        self.assertTrue(result.requires_restart)
        self.assertIn("未找到更新器", result.error)

    def test_updater_installs_regular_file_and_writes_installed_manifest(self) -> None:
        new_payload = b"new file"
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["LOCALAPPDATA"] = str(Path(tmp) / "local")
            app_dir = Path(tmp, "app")
            staging = Path(tmp, "staging")
            app_dir.mkdir()
            staging.mkdir()
            Path(app_dir, "demo.txt").write_bytes(b"old file")
            Path(staging, "demo.txt").write_bytes(new_payload)
            job_path = Path(tmp, "job.json")
            job_path.write_text(
                json.dumps(
                    {
                        "version": "0.2.0",
                        "app_dir": str(app_dir),
                        "staging_dir": str(staging),
                        "exe_path": str(app_dir / "GMT-N.exe"),
                        "files": [
                            {
                                "path": "demo.txt",
                                "sha256": _sha256_bytes(new_payload),
                                "install": "copy",
                            }
                        ],
                        "delete": [],
                        "manifest": {
                            "version": "0.2.0",
                            "files": [
                                {
                                    "path": "demo.txt",
                                    "sha256": _sha256_bytes(new_payload),
                                    "size": len(new_payload),
                                    "install": "copy",
                                }
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )

            self.assertTrue(updater_main.install_update_job(job_path))
            installed_manifest = json.loads(Path(app_dir, "installed-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(Path(app_dir, "demo.txt").read_bytes(), new_payload)
            self.assertEqual(installed_manifest["version"], "0.2.0")
            self.assertEqual(installed_manifest["files"]["demo.txt"]["sha256"], _sha256_bytes(new_payload))

    def test_updater_merges_config_without_overwriting_user_values(self) -> None:
        defaults = {"CONFIG_VERSION": 5, "SIDEBAR_WIDTH": 270, "VIEW_SIZE": 600}
        defaults_bytes = json.dumps(defaults, ensure_ascii=False).encode("utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["LOCALAPPDATA"] = str(Path(tmp) / "local")
            app_dir = Path(tmp, "app")
            staging = Path(tmp, "staging")
            app_dir.mkdir()
            staging.mkdir()
            Path(app_dir, "config.json").write_text(
                json.dumps({"SIDEBAR_WIDTH": 333, "OLD_ROUTE_LIMIT": 3}),
                encoding="utf-8",
            )
            Path(staging, "config.json").write_text(json.dumps(defaults, ensure_ascii=False), encoding="utf-8")
            job_path = Path(tmp, "job.json")
            job_path.write_text(
                json.dumps(
                    {
                        "version": "0.2.0",
                        "app_dir": str(app_dir),
                        "staging_dir": str(staging),
                        "exe_path": str(app_dir / "GMT-N.exe"),
                        "files": [
                            {
                                "path": "config.json",
                                "sha256": _sha256_bytes(defaults_bytes),
                                "install": "merge_config",
                            }
                        ],
                        "delete": [],
                        "obsolete_config_keys": ["OLD_ROUTE_LIMIT"],
                        "manifest": {"version": "0.2.0", "files": []},
                    }
                ),
                encoding="utf-8",
            )

            self.assertTrue(updater_main.install_update_job(job_path))
            merged = json.loads(Path(app_dir, "config.json").read_text(encoding="utf-8"))

        self.assertEqual(merged["CONFIG_VERSION"], 5)
        self.assertEqual(merged["SIDEBAR_WIDTH"], 333)
        self.assertEqual(merged["VIEW_SIZE"], 600)
        self.assertNotIn("OLD_ROUTE_LIMIT", merged)

    def test_updater_rolls_back_when_replace_fails(self) -> None:
        new_payload = b"new file"
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["LOCALAPPDATA"] = str(Path(tmp) / "local")
            app_dir = Path(tmp, "app")
            staging = Path(tmp, "staging")
            app_dir.mkdir()
            staging.mkdir()
            target = Path(app_dir, "demo.txt")
            target.write_bytes(b"old file")
            Path(staging, "demo.txt").write_bytes(new_payload)
            job_path = Path(tmp, "job.json")
            job_path.write_text(
                json.dumps(
                    {
                        "version": "0.2.0",
                        "app_dir": str(app_dir),
                        "staging_dir": str(staging),
                        "exe_path": str(app_dir / "GMT-N.exe"),
                        "files": [
                            {
                                "path": "demo.txt",
                                "sha256": _sha256_bytes(new_payload),
                                "install": "copy",
                            }
                        ],
                        "delete": [],
                        "manifest": {"version": "0.2.0", "files": []},
                    }
                ),
                encoding="utf-8",
            )

            with patch("scripts.updater_main.os.replace", side_effect=OSError("locked")):
                with self.assertRaises(OSError):
                    updater_main.install_update_job(job_path)

            self.assertEqual(target.read_bytes(), b"old file")


if __name__ == "__main__":
    unittest.main()
