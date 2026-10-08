# B 站／斗鱼／抖音直播弹幕发送脚本（macOS）

脚本使用 **Edge 中已经打开并登录**的 B 站或斗鱼直播网页，不启动新浏览器，也不要求再次登录。它自动识别当前活动标签页的平台和直播间，切换平台或房间时丢弃旧房间尚未发送的语音。B 站在标签页内请求直播弹幕接口；斗鱼使用页面自己的弹幕发送控件，按 DOM 定位，不依赖屏幕坐标。网页登录凭据只在浏览器标签页内使用，不会写入文件或传回 Python。

支持两种内容来源：文本文件逐行发送，或把麦克风语音经阿里云百炼实时识别后自动发送。语音模式仅发送模型判定为**完整句子**的结果。

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

如果辅助程序不存在或源代码更新，脚本会把项目内的 `douyin_ax.swift` 编译成 `.venv/bin/douyin_ax`，需要 macOS 的 Xcode Command Line Tools。如提示没有辅助功能权限，请到“系统设置 → 隐私与安全性 → 辅助功能”允许当前终端，然后重新运行。脚本通过系统辅助功能读取客户端直播页地址或内嵌直播页面的房间编号，并查找弹幕输入框；发送时暂时聚焦抖音，用真实粘贴和回车操作，随后恢复原先的前台应用。它不会从客户端提取登录凭据，也不需要重新登录。关闭直播间或切换房间时会停止向旧房间发送；客户端彻底退出时会继续监听语音，但跳过没有直播间期间识别的话。

抖音客户端目前以“已触发发送”报告结果。这个状态表示内容已输入并按下回车，不代表服务器最终展示。若客户端全屏模式移除了弹幕输入框，`--inspect` 会显示“可发送：否”；退出该模式后可继续。已存在的手写草稿会被保留，此时脚本不会发送新语音。

### 客户端直连接口验证（2026-10-08）

当前版本**没有实现**不依赖输入框的抖音 Mac 客户端发送。抖音开放平台的[直播间评论互动能力](https://developer.open-douyin.com/docs/resource/zh-CN/interaction/jierushuoming/hudongshuju/pinglunshuju/)只提供接收观众评论的能力；[抖音直播 SDK 接入说明](https://developer.open-douyin.com/docs/resource/zh-CN/dop/ability/douyin-live-sdk/douyin-live-sdk/interface-and-function)只向接入方提供 Android SDK，并未公开控制现有 Mac 客户端发送评论的接口。不能把这两种能力当作客户端发送 API。

已获许可对已登录的抖音 Mac 8.7.0 客户端临时使用 Electron 的 `--remote-debugging-port` 启动。参数到达了客户端主进程，但实际没有监听端口，因此只读探针 `douyin_cdp.py` 无法进入当前直播页，也就不能验证客户端自己的发送请求。探针不读取凭据、不发送内容，不属于正式发送链路。调试实例已退出，客户端已恢复普通启动，临时端口已关闭。未经验证的 `webcast/room/chat` 请求不能用“接口返回成功”代替弹幕实际展示。

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

打开项目里的 `config.local.json`，在 `dashscope_api_key` 的两个引号之间填入百炼 API Key。`model` 当前为 `paraformer-realtime-v2`。该文件已加入 `.gitignore`，权限设为仅当前用户可读写。

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
- 语音模式持续向百炼上传麦克风音频，并按实际调用计费。识别失败、发送失败或待发送句子积压超过 50 条时会停止。`Ctrl+C` 会立即结束，未发送的句子不会补发。
- 脚本使用你自己的已登录账号，发送频率和内容应遵守直播间及平台规则。
