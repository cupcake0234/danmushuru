# 项目文件位置

- 本项目生成的模型、配置、扩展副本、缓存、临时文件和构建产物均放在项目目录内，不写入 C 盘的用户目录或系统临时目录。系统字体、系统 DLL 和已安装工具可正常读取。
- 应用数据使用 `project_paths.py`：`data/` 保存配置、模型和扩展，`.tools/tmp/` 保存临时文件，`.tools/cache/` 保存工具缓存。
- 执行 Python、pip、uv、PyInstaller 等命令时，使用项目虚拟环境，并将 `TEMP`、`TMP`、`PIP_CACHE_DIR`、`UV_CACHE_DIR`、`PYINSTALLER_CONFIG_DIR` 指向项目内；`build_windows_exe.bat` 已配置这些路径。
- Windows 发布使用目录打包，入口为 `dist/DanmuLive.exe`，运行库为 `dist/_internal/`，分享时一起保留，避免单文件打包向 C 盘解压。
