# Windows 打包说明

本项目按 PyInstaller 的 `onedir` 方式打包。最终给用户的是整个 `dist/GMT-N` 文件夹，用户双击 `GMT-N.exe` 即可启动。

## 一键构建

在项目根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1 -Clean
```

脚本会自动安装 `requirements.txt` 里的运行依赖和 `pyinstaller`，然后生成：

```text
dist/GMT-N/GMT-N.exe
```

PyInstaller 配置文件放在 `packaging/` 下；请通过 `scripts/build_windows.ps1` 构建，脚本会使用正确的 spec 路径。独立更新器源码位于 `scripts/updater_main.py`。

## 发布时包含

请把整个 `dist/GMT-N` 文件夹压缩发给用户，不要只发 exe。文件夹里会包含：

- `GMT-N.exe`
- `maps/README.md`（底图目录按用户数据保护；程序默认不预置底图）
- `config.json`
- `routes/`
- `annotations/`
- `tools/points_get/`
- `tools/points_icon/`
- PyInstaller 运行所需的 `_internal/` 等文件

这些数据文件需要保持和 exe 在同一个发布文件夹里，因为程序会把窗口设置、路线进度、标注数据写回这里。

不要把根目录 `big_map.png` 或 `big_map_17173.png` 打进发布包。程序默认不预选底图或标注文件，用户需要把底图放入 `maps/`、把标注文件放入 `annotations/` 或在设置中导入后自行选择。更新清单默认保护 `maps/`、`annotations/`、`routes/`、`tools/`，只默认发布 `maps/卡洛西亚大陆/big_map_new.png`；如需发布一次性资源可通过 `--include` 显式加入。更新清单会默认推送删除旧版根目录底图和 17173 旧底图。

## 用户使用方式

1. 解压发布包。
2. 双击 `GMT-N.exe`。
3. 首次启动按提示框选游戏小地图区域。

如果用户之后要迁移到另一台电脑，直接复制整个 `GMT-N` 文件夹即可保留路线、设置和进度。
