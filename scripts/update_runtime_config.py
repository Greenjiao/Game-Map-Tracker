"""将当前版本追加到 runtime_config.json 的 APP_ENABLE_VERSIONS 数组中。

用法：
  py -3 scripts/update_runtime_config.py GMT-N-0.1.7
"""

import json
import sys
from pathlib import Path

RUNTIME_CONFIG_PATH = Path(__file__).resolve().parent.parent / "runtime_config.json"


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: py -3 scripts/update_runtime_config.py <AppEnabledVersion>", file=sys.stderr)
        return 1

    version = sys.argv[1].strip()
    if not version:
        print("版本号不能为空", file=sys.stderr)
        return 1

    config_path = RUNTIME_CONFIG_PATH
    if not config_path.exists():
        print(f"未找到 {config_path}，跳过", file=sys.stderr)
        return 0

    try:
        raw = config_path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            text = raw[3:].decode("utf-8")
        else:
            text = raw.decode("utf-8")
        data = json.loads(text)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"读取 {config_path} 失败: {exc}", file=sys.stderr)
        return 1

    if not isinstance(data, dict):
        print("runtime_config.json 格式错误，应为 JSON 对象", file=sys.stderr)
        return 1

    versions = data.setdefault("APP_ENABLE_VERSIONS", [])
    if not isinstance(versions, list):
        versions = []
        data["APP_ENABLE_VERSIONS"] = versions

    if version in versions:
        print(f"版本 {version} 已在列表中，跳过。")
        return 0

    versions.append(version)
    config_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"已追加版本：{version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
