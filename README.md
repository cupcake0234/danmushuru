# DanmuLive · 直播语音弹幕控制台

DanmuLive 是一个将麦克风语音转换为直播弹幕的桌面工具，支持哔哩哔哩、斗鱼和抖音直播网页。你可以手动输入文字，也可以通过语音识别自动发送；开启自动跟随后，发送目标会随浏览器正在观看的直播间切换。

Windows 版通过浏览器扩展连接已经打开并登录的 Edge / Chrome 标签页，沿用浏览器中的登录状态。本地语音识别使用 SenseVoiceSmall INT8，可在 CPU 上离线运行，也可选择阿里云百炼进行云端识别。

## 主要功能

- **多平台直播间识别**：发现 Edge / Chrome 中打开的 B 站、斗鱼和抖音直播页，显示房间信息与可发送状态。
- **文字与语音弹幕**：支持手动输入、麦克风语音识别，以及命令行逐行发送文本文件。
- **手动选择与自动跟随**：固定选择一个直播间，或自动跟随最近使用的浏览器活动直播页。
- **本地与云端识别**：支持本地 SenseVoice 和阿里云百炼；本地模式无需 API Key，音频不上传。
- **模型一键安装**：支持下载进度、取消、重试和 SHA-256 校验，优先从魔搭下载，失败后切换 Hugging Face。
- **发送队列与日志**：识别结果按顺序处理，可调整发送间隔，查看识别文本、排队状态、发送结果与失败原因，复制日志。
- **完整便携包**：包含程序、运行库、浏览器扩展和本地模型，无需安装 Python；数据、缓存与临时文件保存在程序目录内。

## 运行环境

| 项目 | 要求 |
| --- | --- |
| Windows 便携版 | Windows 10 / 11，Intel / AMD x64；不适用于 32 位 Windows |
| 浏览器 | Edge 或 Chrome，并加载项目附带的浏览器扩展 |
| 本地识别 | CPU 运行，无需 CUDA；语音输入需要可用的麦克风 |
| 网络 | 观看直播、发送弹幕、首次下载模型和云端识别需要联网；本地识别可离线运行 |
| 安装位置 | 有写入权限的非 C 盘目录；完整包解压后约 363 MiB，另需保留运行空间 |

仓库保留 macOS 命令行和客户端辅助代码，详见[历史使用与平台适配记录](docs/legacy-notes.md)。Windows 便携包面向网页直播场景。

## 快速开始

### 1. 解压并启动

当前完整便携包位于：

```text
release/DanmuLive-Windows-x64-Portable-20261125.zip
```

将 ZIP 整体解压到 D 盘或其他非 C 盘文件夹，双击 `DanmuLive.exe` 或 `启动程序.bat`。

请保留整个文件夹中的 `_internal`、`data` 和许可证文件。只复制 exe 会缺少运行库与模型。

### 2. 连接浏览器

1. 在 Edge 或 Chrome 中登录直播平台，打开需要使用的直播间。
2. 点击控制台顶部的 **浏览器扩展**，打开对应浏览器的扩展管理页。
3. 开启浏览器的 **开发者模式**，选择 **加载解压缩的扩展程序**。
4. 选择安装窗口显示的扩展目录：`data/browser_extension_ready`。
5. 保持扩展启用，回到控制台查看直播间列表；必要时点击 **刷新房间**。

文件夹选择窗口可能隐藏目录中的文件，直接选中扩展文件夹即可。Edge 和 Chrome 需要分别加载一次扩展。

扩展与桌面程序通过本机 `127.0.0.1:8765` 通信。更新扩展文件后，需要在浏览器扩展管理页点击 **重新加载**。

### 3. 发送文字或语音

选择一个可发送的直播间，在 **手动弹幕** 中输入文字并点击 **发送弹幕**。

使用语音时，进入 **语音设置**，选择 **本地 SenseVoiceSmall INT8**。完整便携包已包含模型，可以直接保存配置；源码或不含模型的构建可点击 **一键安装模型**。返回主界面点击 **开始监听**，说话并在句子结束后稍作停顿，程序会识别并按队列发送。点击 **停止监听** 可结束语音发送。

运行日志会显示识别内容、排队状态和发送结果。“已触发网页发送”表示已经操作网页发送控件，弹幕最终是否展示以直播间为准。

## 手动选择与自动跟随

| 模式 | 行为 |
| --- | --- |
| 手动选择 | 在列表中固定选择一个直播间，适合持续向指定房间发送弹幕 |
| 自动跟随 | 跟随最近使用的 Edge / Chrome 窗口中的活动直播标签页，切换观看的直播间时自动更新目标 |

自动模式下切回控制台会保留最近的浏览器目标。活动页不是直播间、浏览器最小化或连接不可用时，自动监听会等待或暂停；恢复可发送的直播页后继续。点击 **停止监听** 会取消自动恢复。

切换房间时会清空旧房间尚未发送的语音队列，并重新开始收音。已经交给网页执行的发送仍可能完成。自动模式下手动点击其他房间会切回手动选择。

## 语音识别

| 方案 | 运行方式 | 配置 |
| --- | --- | --- |
| SenseVoiceSmall INT8 | 本机 CPU 离线识别，音频不上传 | 本地模型目录，无需 API Key |
| 阿里云百炼 | 联网识别，音频发送到配置的云端服务 | 自行填写 API Key 和 WebSocket 地址 |

本地模型支持中文、粤语、英语、日语和韩语，可选择自动检测或指定语言。模型文件与词表合计约 **228.5 MiB**，保存在：

```text
data/models/sensevoice-small-int8-2024-07-17/
├─ model.int8.onnx
└─ tokens.txt
```

本地模式根据音量与静音时间断句，可在语音设置中调整音量门限。百炼模式使用 `paraformer-realtime-v2`，发送模型判断为完整句子的识别结果。

`DASHSCOPE_API_KEY` 和 `DASHSCOPE_WEBSOCKET_URL` 环境变量只在百炼模式下生效，并优先于文件配置。模型来源与协议保存在完整包的 `third_party_licenses` 中，文件校验值见 `package-manifest.json`。

## 数据保存与移动

```text
程序目录/
├─ DanmuLive.exe                 # 启动入口
├─ _internal/                   # Python、图形界面与本地推理运行库
├─ data/
│  ├─ config.local.json         # 本机设置
│  ├─ browser_extension_ready/  # 浏览器扩展
│  └─ models/                   # 本地模型
├─ .tools/                      # 运行后生成的缓存、临时文件
├─ third_party_licenses/        # 第三方协议与出处
├─ 使用说明.txt
├─ 环境检查.bat
└─ 启动程序.bat
```

移动或分享时请复制整个文件夹。保存在 `data` 内的模型路径使用相对路径，保存语音设置后仍可随文件夹移动。浏览器可能记着旧的扩展路径，移动后需要移除旧扩展，再加载新位置的 `data/browser_extension_ready`。

本项目的应用数据和构建产物均保存在项目目录内：配置、模型和扩展使用 `data/`，临时文件使用 `.tools/tmp/`，依赖及构建缓存使用 `.tools/cache/`。运行库直接从 `_internal/` 加载，启动时不向 C 盘解压。

项目内的 `dist/DanmuLive.exe` 使用项目根目录作为数据根目录；独立便携包使用 exe 所在目录作为数据根目录。路径统一由 [project_paths.py](project_paths.py) 管理。

分享包使用空 Key 的新配置。转发自己使用过的文件夹前，请清空 `data/config.local.json` 中的个人云端 Key。

## 从源码运行

以下命令在项目根目录的 PowerShell 中执行。当前构建使用 Python 3.12 x64，请先准备好对应的 Python 环境。

```powershell
# 将本项目的临时文件和工具缓存放在项目内部
$taskRoot = (Get-Location).Path
$env:TEMP = Join-Path $taskRoot '.tools\tmp'
$env:TMP = $env:TEMP
$env:PIP_CACHE_DIR = Join-Path $taskRoot '.tools\cache\pip'
$env:UV_CACHE_DIR = Join-Path $taskRoot '.tools\cache\uv'
$env:PYINSTALLER_CONFIG_DIR = Join-Path $taskRoot '.tools\cache'
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null

py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 首次创建本地配置，保留已有配置
New-Item -ItemType Directory -Path data -Force | Out-Null
if (-not (Test-Path data\config.local.json)) {
    Copy-Item config.local.example.json data\config.local.json
}

.\.venv\Scripts\python.exe danmu.py --gui
```

安装依赖后，也可双击 [start_gui.bat](start_gui.bat)。首次使用源码版本时，可在语音设置中安装本地模型。

### 命令行示例

```powershell
# 只检查直播页面，不发送
.\.venv\Scripts\python.exe danmu.py --browser edge --inspect

# 发送一条文字
.\.venv\Scripts\python.exe danmu.py --browser edge --message "你好，直播间！"

# 逐行发送 UTF-8 文本文件，间隔 20 秒
.\.venv\Scripts\python.exe danmu.py --browser edge --interval 20 messages.txt

# 只识别麦克风语音并显示文本
.\.venv\Scripts\python.exe danmu.py --mic --voice-provider sensevoice --transcribe-only

# 查看全部参数
.\.venv\Scripts\python.exe danmu.py --help
```

文本文件中的空行与以 `#` 开头的行会跳过。命令行文本发送默认间隔 20 秒、最少 10 秒；图形界面有独立的发送间隔设置。需要明确选择目标直播间时，使用图形界面。

## 构建 Windows 便携包

在上述项目环境中安装构建工具，并确认本地模型已下载到 `data/models`：

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller

# 独立构建到 .tools/portable-dist，不覆盖正在运行的原程序
.\build_windows_exe.bat DanmuLive --stage-only

# 生成包含模型的完整文件夹、ZIP 和 SHA-256 校验文件
.\.venv\Scripts\python.exe scripts\package_windows_portable.py
```

产物位于 `release/`，包含运行库、本地模型、浏览器扩展、空 Key 配置、使用说明、环境检查入口和第三方协议。再次打包时，可用 `--output release/DanmuLive-Windows-x64-Portable-new` 指定一个新的输出目录。

只需更新项目内的 `dist/DanmuLive.exe` 时，可关闭原程序后运行 `build_windows_exe.bat`。`_internal` 必须与 exe 一起保留。

## 验证与排查

完整包内可双击 **环境检查.bat**，结果写入包内的 `self-check.json`。检查包括图形运行库、音频运行库、扩展文件、模型 SHA-256 和 CPU 离线推理；不会打开麦克风、连接浏览器或发送弹幕。

| 情况 | 处理方法 |
| --- | --- |
| 未发现直播间或一直等待活动页信息 | 确认扩展已启用、直播页已打开；更新扩展后点击重新加载，再刷新房间 |
| 扩展目录看起来为空 | 在文件夹选择窗口中选中整个扩展目录；该窗口可能不显示文件 |
| 找不到模型 | 运行环境检查，确认两个模型文件存在；需要时在语音设置中一键安装 |
| 麦克风没有识别结果 | 检查系统麦克风权限与输入音量，尝试调整音量门限 |
| 移动文件夹后连接失效 | 在浏览器中重新加载新位置的扩展目录 |
| 程序缺少 DLL 或无法启动 | 重新完整解压 ZIP，保留 `_internal`，查看环境检查结果 |

截至 2026-11-25，已通过 122 项 Python 测试、7 项扩展测试，以及完整 ZIP 解压到含中文和空格路径后的实际中文离线识别检查。自动化测试可在配置好项目内缓存路径的环境中运行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --test tests/test_extension_auto_follow.js
```

## 项目结构

```text
danmushuru/
├─ windows_app.py              # Windows 图形界面
├─ windows_theme.py            # 界面组件与浅色样式
├─ windows_browser.py          # 浏览器发现与网页发送
├─ windows_extension_bridge.py # 本机扩展通信
├─ windows_extension_setup.py  # 扩展准备与安装引导
├─ voice.py                    # 语音配置与输入流程
├─ local_voice.py              # 本地识别与静音断句
├─ model_store.py              # 模型下载与校验
├─ project_paths.py            # 数据与缓存路径
├─ portable_check.py           # 便携环境检查
├─ danmu.py                    # 命令行入口
├─ browser_extension_ready/    # 浏览器扩展
├─ web_actions/                # 平台网页操作脚本
├─ platforms/                  # 客户端辅助代码
├─ scripts/                    # 扩展、图标及便携包构建脚本
├─ tests/                      # 自动化测试
├─ docs/                       # 历史使用与适配记录
├─ data/                       # 本机应用数据，不提交版本控制
├─ dist/                       # 开发构建输出
└─ release/                    # 完整便携包
```
