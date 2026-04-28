"""Write the clean release config.json from code defaults."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config_defaults import DEFAULT_CONFIG  # noqa: E402


def write_default_config(path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        json.dump(copy.deepcopy(DEFAULT_CONFIG), handle, indent=4, ensure_ascii=False)
        handle.write("\n")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write clean GMT-N default config.json.")
    parser.add_argument("output", help="Output config.json path")
    args = parser.parse_args(argv)
    target = write_default_config(args.output)
    print(f"Wrote default config: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
