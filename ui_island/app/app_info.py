"""Application identity and release update settings."""

from __future__ import annotations

APP_NAME = "GMT-N"
APP_VERSION = "0.1.5"
APP_FORMAT_VERSION = f"{APP_NAME}-{APP_VERSION}"
APP_ENABLE_VERSIONS = [APP_FORMAT_VERSION]

APP_UPDATE_CHANNEL = "update"
APP_UPDATE_MANIFEST_URLS_BY_CHANNEL = {
    "update": (
        "https://gitee.com/qingjiao123/Game-Map-Tracker/raw/main/docs/update/app-manifest.json",
        "https://greenjiao.github.io/Game-Map-Tracker/update/app-manifest.json",
    ),
    "test": (
        "https://gitee.com/qingjiao123/Game-Map-Tracker/raw/main/docs/test/app-manifest.json",
        "https://greenjiao.github.io/Game-Map-Tracker/test/app-manifest.json",
    ),
}
APP_UPDATE_MANIFEST_URLS = APP_UPDATE_MANIFEST_URLS_BY_CHANNEL.get(
    APP_UPDATE_CHANNEL,
    APP_UPDATE_MANIFEST_URLS_BY_CHANNEL["update"],
)
