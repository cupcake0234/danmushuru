# B 站／斗鱼／抖音直播弹幕发送脚本（macOS / Windows）

Windows 控制面板使用 **Edge 或 Chrome 中已经打开并登录**的抖音、斗鱼、B 站直播网页，不启动新浏览器，也不要求再次登录。安装项目附带的浏览器连接扩展后，应用能在后台读取所有已打开的直播标签页并向选中的标签页发送弹幕；网页登录凭据只留在浏览器中，不会写入文件。

支持两种内容来源：文本文件逐行发送，或把麦克风语音识别后自动发送。语音可选择 **本地 SenseVoiceSmall INT8** 或阿里云百炼；本地模式按静音切句，百炼模式只发送模型判定为**完整句子**的结果。

## 项目目录

```text
danmushuru/
├─ danmu.py、windows_app.py、voice.py、windows_*.py  # 程序入口与核心逻辑
├─ start_gui.bat、start.command、build_windows_exe.bat  # 启动与构建入口
├─ assets/                   # 图标源素材
├─ web_actions/              # 三个平台的网页操作脚本源文件
├─ browser_extension_ready/  # 可直接加载到浏览器的扩展
├─ platforms/                # macOS 与 Windows 客户端辅助代码
├─ scripts/                  # 扩展构建脚本
├─ tests/                    # 自动化测试
└─ dist/                     # 构建出的 Windows exe 与配套文件
```

`config.local.json` 是本机私有配置；`config.local.example.json` 是可分享的模板。`.venv/` 和 `.tools/` 是本机环境与构建工具目录。

## Windows 网页直播控制面板

### Windows 可执行文件

直接双击 `dist\DanmuLive.exe` 打开控制面板，不需要运行 Python 命令。`dist\_internal` 是必需的运行库目录，需与 exe 一起保留或分享。程序采用目录打包，启动时不会向 C 盘临时目录解压运行库。首次点击“安装浏览器扩展”时，应用会将扩展准备到项目的 `data\browser_extension_ready`，并打开浏览器扩展管理页。扩展安装并启用后，面板会自动显示已打开的直播间。旧版扩展若从 C 盘加载过，迁移后需在浏览器扩展页重新加载这个新目录。

手动弹幕不需要语音配置。点击窗口中的“语音设置”可选择本地 SenseVoice 或百炼。本地模式选择包含 `model.int8.onnx` 和 `tokens.txt` 的目录即可，不需要 API Key。百炼模式可填写 API Key 和 WebSocket 地址，模型为 `paraformer-realtime-v2`。窗口保存的配置位于项目的 `data\config.local.json`，下次开始监听时生效，不会嵌入 exe。首次使用前仍兼容项目根目录或 `dist` 中的旧配置，之后保存到 `data`。旧配置没有 `voice_provider` 时仍使用百炼。`config.local.example.json` 是空 Key 的本地模式模板；`DASHSCOPE_API_KEY` 和 `DASHSCOPE_WEBSOCKET_URL` 只在百炼模式生效。

模型、配置和扩展均保存在项目的 `data` 目录；程序临时文件使用 `.tools\tmp`，构建工具和依赖缓存使用 `.tools\cache`。这些路径不再使用用户的 AppData 或 C 盘临时目录。从项目中运行 `dist\DanmuLive.exe` 时使用项目根目录；将 `dist` 整体分享到其他位置时，接收方的数据和缓存保存在该目录内部。

完整 Windows x64 分享包可用 `build_windows_exe.bat DanmuLive --stage-only` 构建后，再运行 `.venv\Scripts\python.exe scripts\package_windows_portable.py` 生成到 `release`。它包含 exe、运行库、已校验的本地模型、浏览器扩展、空 Key 的新配置、使用说明与许可证，不复制个人配置。整个文件夹移动后，保存在 `data` 内的模型路径仍可解析；也可双击包内的“环境检查.bat”检查实际运行库和模型推理。

修改 Python 代码后，可运行 `build_windows_exe.bat` 重新生成 exe。构建需要项目虚拟环境中安装 PyInstaller 和 `requirements.txt` 中的依赖；构建脚本会把网页脚本、浏览器扩展和本地推理运行库放入 exe。模型文件仍从外部目录读取。用户配置保存在 exe 外，重新打包不会覆盖窗口中保存的配置。

主界面使用常规浅色样式：浅灰背景、白色分区、蓝色按钮与选中态，输入框保留 1 像素的淡边线。程序不加载背景图片，exe 也不打包原背景图。房间列表支持鼠标、方向键和滚轮；日志支持滚动、拖选、Ctrl+C 复制选中文字，以及“复制日志”复制全部内容。可运行 `build_windows_exe.bat DanmuLive-standard` 生成另一个文件名的 exe，适用于旧版正在运行时打包。

要在**不切换标签页**的情况下识别全部直播页，首次使用时点击窗口中的“安装浏览器扩展”：

1. 在引导窗口点击“打开 Edge 扩展页”或“打开 Chrome 扩展页”。应用会同时打开准备好的扩展目录，也可以点“复制路径”。
2. 在浏览器扩展管理页开启“开发者模式”，点“加载解压缩的扩展程序”，选择引导窗口显示的目录。如果 Edge 和 Chrome 都在用，分别在两个浏览器里加载一次。浏览器安全机制要求这一步在浏览器内确认，应用不能静默代替安装。
3. 保持扩展启用。以后只需打开直播网页并启动应用，就会列出所有已打开的抖音、斗鱼、B 站直播标签页，包括后台标签页。扩展与应用只通过本机 `127.0.0.1:8765` 通信。

更新 exe 后，在窗口中再点一次“安装浏览器扩展”以更新固定目录里的文件，并在 Edge 或 Chrome 的扩展管理页点该扩展的“重新加载”。只重启 exe 不会刷新浏览器中已运行的扩展。

选择一个“可发送”的房间，点“开始监听”即可将麦克风识别的完整句子发到所选直播间，点“停止监听”可随时停止；也可以手动发送。扩展在所选标签页的页面内执行发送逻辑，发送前重新核对房间地址，扫描和发送都不切换标签页。应用每 5 秒更新一次房间列表，新开或关闭直播页无需手动刷新。

直播间列表上方提供“手动选择 / 自动跟随”两种模式，启动时默认手动选择：

- **手动选择**：在列表中点击目标直播间，目标保持固定；监听中手动换房间会停止原监听。
- **自动跟随**：自动选中最近使用的 Edge 或 Chrome 窗口中的活动直播标签页，多个浏览器按最近使用时间判断。切回控制台时保留这个目标；切到其他直播间时自动更换目标。浏览器最小化、活动页不是直播间或扩展连接过期时暂停，不会回退到其他后台直播间。焦点信息约每秒更新，直播页状态检查可能再需要几秒。
- 自动模式中可先点“开始监听”等待直播间；找到可发送的目标后开始收音，离开直播页时暂停，回到直播页后自动恢复。切房间会清空旧房间尚未发送的语音，并重新开始收音；已交给网页执行的发送仍可能完成。发送前还会核对活动直播页。点击“停止监听”会取消自动恢复。
- 自动模式下点击列表中其他房间，会切回手动选择；也可直接点击“手动选择”保留当前目标。

自动跟随优先使用 **0.2.0 或更新版浏览器扩展**上报的活动标签页。扩展尚未重新加载或没有上报时，Windows 会读取最前面的可见浏览器窗口，将活动页标题与扩展已经发现的直播页匹配，兼容 Edge 的“和另外 N 个页面”和个人资料后缀；标题不能唯一匹配时尝试读取地址栏。检测只读取窗口信息，不切换浏览器标签页。多个同名直播标签页无法区分时会提示重新加载扩展，不会随意挑选。

更新后可点击控制台“安装浏览器扩展”更新文件，再到 Edge/Chrome 扩展管理页对“直播弹幕控制台连接器”点一次“重新加载”，启用精确的标签页识别；不需要重新登录直播网站。扩展只向本机发送直播页信息；非直播页的 URL 和标题不会发送。界面会显示当前等待原因或 Windows 后备识别状态。

窗口底部的运行日志按毫秒时间追加显示语音识别的完整句子、排队和准备发送的文本、网页发送结果及失败原因。识别到的句子按顺序发送，默认间隔 1 秒；可在控制台中设为 0 秒，以便上一条发送完成后立即尝试下一条。Windows 控制台的语音断句静音等待为 500 毫秒。直播页暂时不可发送时会保留队列，页面恢复后继续尝试。日志仅保留在当前窗口中，关闭应用后不会写入文件；“网页发送已触发”表示已操作网页发送控件，最终是否展示以直播间为准。

未安装扩展时，面板仍可通过 Windows 辅助功能读取各浏览器窗口的活动标签页；这只能作为有限的兼容方式，不能满足“全部直播页”的要求。网页发送结果中的 `triggered` 表示已触发网页按钮，不能代替直播间实际展示确认。

也可以从项目目录运行：

```powershell
.\.venv\Scripts\python.exe danmu.py --gui
```

也可以双击 [start_gui.bat](start_gui.bat)。本地语音监听无需 API Key；手动发送和房间扫描不需要语音配置。

命令行仍可用 `--browser edge` 或 `--browser chrome` 发送文本；Windows 上会选择扫描到的第一个可发送直播页。需要选择目标时使用控制面板。

## 抖音 Windows 客户端

Windows 客户端适配暂时搁置；项目仍保留 `platforms/windows/douyin_windows.py` 诊断后端。Windows 网页端使用上面的控制面板。macOS 继续使用 `platforms/macos/douyin_ax.swift` 客户端适配。

`--diagnose` 在 Windows 客户端会额外输出 `controlTree` 和当前 UIA 焦点链 `focusedChain`。它只包含控件类型、名称、自动化 ID、类名、ARIA/Legacy 角色、可见/可用/可聚焦状态、可用 Pattern 和文本长度，不输出输入框或草稿的实际内容。抖音有时会把输入框暴露成无名称的非标准控件；当树中只有一个空的可写 `ValuePattern` 控件时，程序会安全地将它作为弹幕输入框；如果输入框当前有焦点，也会沿 UIA 父级链检查其草稿状态，避免误覆盖。发送按钮支持 `InvokePattern` 和 `LegacyIAccessible.DoDefaultAction`，仍不会使用鼠标或键盘模拟。

如果诊断显示 `renderingSurfaceOnly: true`，并且 `nativeChildren` 只有 `Intermediate D3D Window`，说明当前抖音 Windows 客户端没有向外暴露直播文档、输入框或发送按钮的 UI Automation 接口。程序会停止发送，不会把 PowerShell 或其他窗口的 `Edit` 控件误当成弹幕输入框。可以关闭客户端后尝试使用 Chromium 的 `--force-renderer-accessibility` 启动开关重新打开客户端；该开关是否被当前抖音版本保留需要实测，程序不会自动重启或修改客户端进程。

先安装 Python 3.10 或更新版本，再在项目目录运行（PowerShell）：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

本机已创建项目虚拟环境并安装依赖，可以直接测试：

1. 从任务栏或托盘打开抖音主窗口，登录并进入直播间，显示弹幕输入框。隐藏到托盘时无法识别；测试期间不要手动切换焦点或输入草稿。
2. 运行只读检查，只有“可发送：是”才进行下一步。已识别房间但未匹配到输入框或发送按钮时，诊断会保留房间号；inputCandidates / sendButtonCandidates 列出控件类型、匹配来源、启用状态及内容是否可读，不输出草稿内容：

```powershell
.\.venv\Scripts\python.exe danmu.py --browser douyin --inspect
.\.venv\Scripts\python.exe danmu.py --browser douyin --diagnose
```

3. 试发一条，并在直播间里确认它实际出现：

```powershell
.\.venv\Scripts\python.exe danmu.py --browser douyin --message "测试弹幕"
```

4. 单条验收后，可以发送文本文件或接入麦克风：

```powershell
.\.venv\Scripts\python.exe danmu.py --browser douyin --limit 1 messages.txt
.\.venv\Scripts\python.exe danmu.py --browser douyin --limit 1
```

麦克风模式需配置本地模型目录或百炼 API Key（见后文）；单条文本和只读诊断不需要。客户端诊断或旧命令行模式请直接运行 `danmu.py --browser douyin --inspect`；Windows 网页端使用前面的控制面板。

输入框已有草稿、直播间身份不明确、多个窗口无法选定、输入或焦点不一致时停止发送。输入框不支持 `ValuePattern`、发送按钮不支持 `InvokePattern` 或按钮不唯一时也会停止，不会退回鼠标或键盘模拟；输入前与调用按钮前重新核对房间和焦点。发送结果只能证明“已调用客户端发送控件”，需要在直播间里实际看到弹幕才能完成验收。客户端未暴露直播文档 URL 时不会把窗口标题或推荐房间链接当作当前房间号。

**验证状态（2026-11-01）**：48 项自动化测试通过，其中包括扩展加载目录不含 Python 缓存的检查。使用临时 Edge 配置实际加载扩展后，静默发现了三个同时打开的直播地址；Chrome 临时无界面加载检查尚未收到扩展快照，Chrome 常规窗口仍需验证。三个平台已登录网页上的弹幕发送与展示也仍需逐一验证。

## 抖音 Mac 客户端

适配已安装并登录的抖音 Mac 客户端（目前按 8.7.0 的直播界面验证）。在客户端打开直播间后，先检查，再用麦克风试发一条：

```bash
.venv/bin/python danmu.py --browser douyin --inspect
.venv/bin/python danmu.py --browser douyin --limit 1
```

确认直播间里出现了弹幕，再持续运行：

```bash
.venv/bin/python danmu.py --browser douyin
```

若 `--inspect` 显示“可发送：否”，输出中的“辅助功能诊断”会列出客户端进程、窗口及直播控件的读取情况；也可以运行 `.venv/bin/python danmu.py --browser douyin --diagnose` 单独查看。诊断只读取控件结构，不发送弹幕。

如果辅助程序不存在或源代码更新，脚本会把项目内的 `platforms/macos/douyin_ax.swift` 编译成 `.venv/bin/douyin_ax`，需要 macOS 的 Xcode Command Line Tools。如提示没有辅助功能权限，请到“系统设置 → 隐私与安全性 → 辅助功能”允许当前终端，然后重新运行。脚本通过系统辅助功能读取客户端直播页地址或内嵌直播页面的房间编号，并查找弹幕输入框；发送时暂时聚焦抖音，用真实粘贴和回车操作，随后恢复原先的前台应用。它不会从客户端提取登录凭据，也不需要重新登录。关闭直播间或切换房间时会停止向旧房间发送；客户端彻底退出时会继续监听语音，但跳过没有直播间期间识别的话。

抖音客户端目前以“已触发发送”报告结果。这个状态表示内容已输入并按下回车，不代表服务器最终展示。若客户端全屏模式移除了弹幕输入框，`--inspect` 会显示“可发送：否”；退出该模式后可继续。已存在的手写草稿会被保留，此时脚本不会发送新语音。

### 客户端直连接口验证（2026-10-08）

当前版本**没有实现**不依赖输入框的抖音 Mac 客户端发送。抖音开放平台的[直播间评论互动能力](https://developer.open-douyin.com/docs/resource/zh-CN/interaction/jierushuoming/hudongshuju/pinglunshuju/)只提供接收观众评论的能力；[抖音直播 SDK 接入说明](https://developer.open-douyin.com/docs/resource/zh-CN/dop/ability/douyin-live-sdk/douyin-live-sdk/interface-and-function)只向接入方提供 Android SDK，并未公开控制现有 Mac 客户端发送评论的接口。不能把这两种能力当作客户端发送 API。

已获许可对已登录的抖音 Mac 8.7.0 客户端临时使用 Electron 的 `--remote-debugging-port` 启动。参数到达了客户端主进程，但实际没有监听端口，因此只读探针 `platforms/macos/douyin_cdp.py` 无法进入当前直播页，也就不能验证客户端自己的发送请求。探针不读取凭据、不发送内容，不属于正式发送链路。调试实例已退出，客户端已恢复普通启动，临时端口已关闭。未经验证的 `webcast/room/chat` 请求不能用“接口返回成功”代替弹幕实际展示。

后续在用户重新打开的直播间（`live.douyin.com/990770600117`）确认：客户端仍能识别直播间和输入框，但应用菜单及直播页右键菜单没有开发者入口。只读检查已安装应用的 Electron fuse wire 为 `11100001`；其中第 4 位 `node_cli_inspect=0`。按 [Electron fuse 文档](https://www.electronjs.org/docs/latest/tutorial/fuses)，主进程的 `--inspect` 和 `SIGUSR1` 调试方式会被禁用。没有更改客户端二进制文件或用户配置。

Windows 对照：从抖音官方 CDN 下载 Windows 8.7.0 完整安装包，SHA-256 与 [Windows Package Manager 清单](https://raw.githubusercontent.com/microsoft/winget-pkgs/master/manifests/b/ByteDance/Douyin/8.7.0/ByteDance.Douyin.installer.yaml)一致。仅静态解包 `main.dll`，读到相同的 fuse wire `11100001`，因此 Windows 版也禁用了主进程 `--inspect`。Windows 版的 `resources/app.asar` 与 Mac 版不同；未在 Windows 上运行客户端，无法据此断定 Windows 版的页面调试端口是否可用，也尚未验证任何直发弹幕的方法。

## 网页准备

1. 在 Edge 打开并登录 B 站 `https://live.bilibili.com/房间号` 或斗鱼 `https://www.douyu.com/房间号`，把直播页设为 Edge 最前面窗口的活动标签页。
2. 在 Edge 菜单栏选择「显示 → 开发者 → 允许来自 Apple Events 的 JavaScript」。首次运行时，macOS 可能要求允许终端控制 Edge。

检查当前页面，不发送：

```bash
python3 danmu.py --inspect
```

## 文本文件模式

创建 UTF-8 文本文件，例如 `messages.txt`，每行一条弹幕。空行和以 `#` 开头的行会跳过。先试发一条：

```bash
python3 danmu.py --limit 1 messages.txt
```

发送全部：

```bash
python3 danmu.py --interval 20 messages.txt
```

按 `Ctrl+C` 停止。默认间隔是 20 秒，最短 10 秒。脚本也支持 `--browser chrome` 或 `--browser safari`。

## 麦克风语音模式

### 本地 SenseVoiceSmall（推荐本机使用）

参考 Coopanion 的 `src/asr/sherpa.ts` 和 `segmenter.ts`：通过 sherpa-onnx 直接加载 SenseVoiceSmall INT8，16 kHz 单声道输入，默认使用两个 CPU 线程和逆文本归一化。无需启动服务、GPU 或访问识别接口。已有模型可直接复用：

```text
D:\Coopanion\data\home\models\desktop-pet\sensevoice-small-int8-2024-07-17\
  model.int8.onnx
  tokens.txt
```

首次使用可在“语音设置”里选择“本地 SenseVoiceSmall INT8”，点击“一键安装模型”。软件会显示下载进度，优先从魔搭 ModelScope 下载，失败后自动尝试 Hugging Face；来源、文件大小和 SHA-256 与 Coopanion 的模型配置一致。全部校验成功后自动填写目录并保存本地识别配置，下次开始监听时生效。下载过程支持取消和重试，重试会复用已校验的完整文件。

模型和词表共约 228.5 MiB，安装在项目的 `data\models\sensevoice-small-int8-2024-07-17\`。安装时联网，识别时离线。分享程序目录后，其他电脑可自行点击安装，不依赖本机的 Coopanion 目录。

也可手动选择已有模型，或将上述两个文件复制到 exe 同目录的 `models/sensevoice-small-int8-2024-07-17/`。未配置目录时，依次查找软件自己的用户模型目录、exe 同目录的模型、已有的 Coopanion 模型。配置也接受 `desktop-pet` 父目录；相对路径以配置文件所在目录为基准。

安装本地运行依赖，随后先只转写测试：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe danmu.py --mic --voice-provider sensevoice --transcribe-only --limit 3
```

换目录时可追加 `--local-model-dir "D:\模型目录"`。在控制面板的“语音设置”里保存本地模式，或在 `config.local.json` 中设置 `"voice_provider": "sensevoice"` 与 `"local_model_dir": "D:/模型目录"`，之后直接启动即可。

`local_language` 默认为 `auto`，可选 `zh/en/ja/ko/yue`；`local_num_threads` 默认为 2；`local_threshold_db` 默认为 -42 dBFS，可在设置窗口调整。收不到轻声时降低门限，背景噪声触发过多时提高门限。按 Coopanion 的方式保留开口前 320 毫秒、要求至少 180 毫秒持续声音；静音达到 `--silence-ms` 后识别，Windows 窗口使用 500 毫秒。持续讲话每 15 秒切一次，避免一直等待结束。录音和推理使用不同线程，积压超限或识别失败会停止监听并显示原因。停止监听会丢弃尚未完成的片段。

API 用法参考 [sherpa-onnx 官方 SenseVoice 示例](https://github.com/k2-fsa/sherpa-onnx/blob/master/python-api-examples/offline-sense-voice-ctc-decode-files.py)。

**本地验证（2026-11-25）**：73 项自动化测试通过，包括设置面板切换、无 Key 保存、静音断句、长语音分段、积压保护和停止后丢弃结果。实际模型成功识别中文样例“开放时间早上9点至下午5点。”，麦克风能够启动并释放。单独打包的运行库检查程序也通过了同一音频的离线识别；`dist/DanmuLive.exe` 已重新构建并包含所需推理模块和 DLL。设置窗口未完成实际视觉检查。

**自动跟随验证（2026-11-25）**：修复了扩展未上报活动页时一直等待的问题，增加 Windows 窗口检测，以及异步列表选择事件不得退出自动模式的检查。回归测试包含旧扩展没有焦点上报时，从桥接服务、浏览器检测、后台任务到实际房间列表连续切换的完整流程。可运行 `.venv\Scripts\python.exe -m unittest discover -s tests -q` 和 `node --test tests/test_extension_auto_follow.js` 复查。

### 百炼云端识别

当前项目的 `.venv` 已安装语音依赖，先激活它：

```bash
source .venv/bin/activate
```

如果换电脑或删除了 `.venv`，在项目目录重新安装：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

如 PyAudio 安装时报缺少 PortAudio，可先运行 `brew install portaudio`，再重试安装。首次录音时，请允许终端访问麦克风。实时转写使用百炼的 `paraformer-realtime-v2` 模型，接口用法见[阿里云 Python SDK 文档](https://help.aliyun.com/zh/model-studio/paraformer-real-time-speech-recognition-python-sdk)。

项目里的 `config.local.json` 已按当前格式填好；如需更换百炼 API Key，修改其中的 `dashscope_api_key`。`model` 当前为 `paraformer-realtime-v2`。该文件已加入 `.gitignore`，权限设为仅当前用户可读写。

默认使用北京地域的 DashScope WebSocket 地址；若你的 Key 属于其他地域，修改配置文件中的 `websocket_url`。也可继续用 `DASHSCOPE_API_KEY` 和 `DASHSCOPE_WEBSOCKET_URL` 环境变量覆盖配置文件中的对应值。不要把 Key 写进脚本或 `messages.txt`。

先只转写、不发送：

```bash
python danmu.py --mic --transcribe-only --limit 3
```

确认识别效果后，先试发一条，再持续运行：

```bash
python danmu.py --limit 1
python danmu.py
```

不传文本文件时，语音监听和发送是默认模式。也可以双击 [start.command](start.command) 启动。程序会持续检查 Edge 当前活动标签页：关闭或离开直播间时继续监听但跳过这段时间的话；打开其他已登录的 B 站或斗鱼直播间后，自动向新房间发送之后说出的内容。切换平台或房间时，旧房间未发送的语音会丢弃。按 `Ctrl+C` 停止。

一句话结束由静音时长判断，默认 800 毫秒，可用 `--silence-ms 1200` 调整。过长句子按每条 20 字拆分，可用 `--max-chars 30` 调整。用 `python danmu.py --list-input-devices` 查看输入设备，再用 `--input-device 编号` 指定麦克风。启动时会打印实际选中的录音设备；如果系统默认输入是 BlackHole、Soundflower 等回传设备，脚本会优先改用实体麦克风，并拒绝直接使用常见回传设备。

如果正在用电脑扬声器播放直播，扬声器的声音仍会被实体麦克风从空气中收进去；音频流里无法可靠区分这部分人声和你说的话。要可靠排除它，请用耳机听直播或关闭直播声音。先运行 `python danmu.py --transcribe-only`，确认只识别你说的话，再自动发送。

## 工作方式与限制

- B 站每条弹幕都重新检查 Edge 当前活动标签页的房间号，再通过房间初始化接口确认真实房间号，最后调用 `api.live.bilibili.com/msg/send`。接口返回 `code: 0` 才显示“已发送”。
- 斗鱼适配目前为试运行：仅在已登录的 `www.douyu.com` 直播页找到弹幕输入区和按钮时发送。控件选择器参考[当前斗鱼网页增强脚本的实现](https://greasyfork.org/en/scripts/580102-douyuex-%E6%96%97%E9%B1%BC%E7%9B%B4%E6%92%AD%E9%97%B4%E5%A2%9E%E5%BC%BA%E6%8F%92%E4%BB%B6-1%E6%97%B6%E5%8E%BB%E9%99%A4%E5%BC%B9%E5%B9%95%E6%9C%AB%E5%B0%BE%E6%95%B0%E5%AD%97/code)。脚本向页面输入文本并触发其发送按钮，日志显示“已触发发送”；这个状态不能证明斗鱼服务器已收下弹幕。输入框已有文字或按钮不可用时不会覆盖或重复发送。即使网页全屏、输入框不在画面内，只要控件仍在页面 DOM 中就能尝试发送；若斗鱼改版后控件被移除，`--inspect` 将显示“可发送：否”。
- 开始发送前发现房间已切换时会取消旧请求；发送过程中切页导致结果未知时不会重发该条。弹幕是否最终展示取决于平台审核、账号状态和直播间设置。
- 网页接口参数可能变化。如果接口拒绝请求，脚本会显示错误并停止，不会自动重发或尝试绕过验证。
- 百炼模式持续向百炼上传麦克风音频，并按实际调用计费；本地 SenseVoice 模式在 CPU 上处理，音频不上传。识别失败、发送失败或待发送句子积压超过 50 条时会停止。`Ctrl+C` 会立即结束，未发送的句子不会补发。
- 脚本使用你自己的已登录账号，发送频率和内容应遵守直播间及平台规则。
