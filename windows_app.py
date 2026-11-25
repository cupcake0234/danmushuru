"""Windows control panel for browser live-room selection and voice listening."""

import ctypes
import math
import os
import queue
import sys
import threading
import time
import tkinter as tk
from collections import deque
from datetime import datetime
from tkinter import filedialog, ttk

from model_store import (MODEL_BYTES, ModelInstallCancelled, install_model,
                         managed_model_dir)
from voice import (DEFAULT_MODEL, DEFAULT_PROVIDER, DEFAULT_WS_URL, VoiceError, VoiceStream,
                   default_local_model_dir, read_settings_file, save_settings)
from windows_browser import WindowsBrowser
from windows_theme import ActivityLog, ModeButton, PhotoButton, PhotoLabel, RoomTable

MAX_VOICE_QUEUE = 100
MISSING_TARGET_GRACE_SECONDS = 30


class WindowsControlPanel:
    def __init__(self, root):
        self.root = root
        self.root.title("直播弹幕控制台")
        scale = self.root.winfo_fpixels("1i") / 96
        width = min(round(1080 * scale), round(self.root.winfo_screenwidth() * 0.9))
        height = min(round(720 * scale), round(self.root.winfo_screenheight() * 0.9))
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(min(round(860 * scale), width), min(round(680 * scale), height))
        self.browser = WindowsBrowser()
        self.rooms = []
        self.selected_key = None
        self.rendering_rooms = False
        self.refreshing = False
        self.listening = False
        self.voice = None
        self.voice_thread = None
        self.stop_voice = threading.Event()
        self.voice_session = 0
        self.last_sent = 0.0
        self.interval = 1.0
        self.listening_target_key = None
        self.target_missing_since = None
        self.voice_pending = deque()
        self.voice_send_busy = False
        self.voice_send_timer = None
        self.voice_waiting_for_room = False
        self.voice_inflight = None
        self.auto_listen_requested = False
        self.auto_follow_busy = False
        self.auto_follow_generation = 0
        self.auto_target_identity = None
        self.auto_hint = "等待浏览器活动直播页。"
        self.jobs = queue.Queue()
        self.last_scan_notice = None
        self._build()
        self.root.after(100, self._drain_jobs)
        self.root.after(200, self.refresh_rooms)
        self.root.after(5000, self._refresh_timer)
        self.root.after(500, self._auto_follow_timer)

    def _build(self):
        colors = {
            "background": "#F5F7FA", "surface": "#FFFFFF", "text": "#263241",
            "muted": "#687586", "border": "#E4E8EF", "accent": "#3B74CD",
            "accent_hover": "#2F63B3", "success": "#347A61", "error": "#B24C5D",
        }
        self.root.configure(bg=colors["background"])
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", background=colors["surface"], foreground=colors["text"],
                        font=("Microsoft YaHei UI", 9), borderwidth=0)
        style.configure("TButton", background="#F0F3F7", foreground=colors["text"],
                        borderwidth=0, focusthickness=0, padding=(12, 7))
        style.map("TButton", background=[("pressed", "#DCE7F7"), ("active", "#E6EDF7")],
                  foreground=[("disabled", "#9AA3AF")])
        style.configure("TEntry", fieldbackground="#FFFFFF", foreground=colors["text"],
                        insertcolor=colors["text"], bordercolor=colors["border"],
                        lightcolor="#FFFFFF", darkcolor="#FFFFFF", borderwidth=1,
                        relief="flat", padding=(6, 4))
        style.map("TEntry", bordercolor=[("focus", "#91B1E0")],
                  fieldbackground=[("readonly", "#F5F7FA")])
        style.configure("TCombobox", fieldbackground="#FFFFFF", background="#F5F7FA",
                        foreground=colors["text"], arrowcolor=colors["muted"], borderwidth=1,
                        bordercolor=colors["border"], lightcolor="#FFFFFF", darkcolor="#FFFFFF", padding=4)
        style.map("TCombobox", fieldbackground=[("readonly", "#FFFFFF")],
                  foreground=[("readonly", colors["text"])], selectbackground=[("readonly", "#FFFFFF")])
        style.configure("TSpinbox", fieldbackground="#FFFFFF", foreground=colors["text"],
                        background="#F5F7FA", arrowcolor=colors["muted"], borderwidth=1,
                        bordercolor=colors["border"], lightcolor="#FFFFFF", darkcolor="#FFFFFF", padding=4)
        style.configure("TCheckbutton", background=colors["surface"], foreground=colors["muted"])
        style.map("TCheckbutton", background=[("active", colors["surface"])])
        style.configure("Horizontal.TProgressbar", background="#79A0DC", troughcolor="#EEF2F7",
                        borderwidth=0, lightcolor="#79A0DC", darkcolor="#79A0DC")
        self.root.option_add("*TCombobox*Listbox.background", "#FFFFFF")
        self.root.option_add("*TCombobox*Listbox.foreground", colors["text"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", "#E5EFFD")

        shell = tk.Frame(self.root, bg=colors["background"], bd=0, padx=10, pady=10)
        self.main_panel = shell
        shell.pack(fill="both", expand=True)
        shell.grid_columnconfigure(0, weight=1)
        shell.grid_rowconfigure(1, weight=2)
        shell.grid_rowconfigure(3, weight=2)

        header = tk.Frame(shell, bg=colors["background"])
        header.grid(row=0, column=0, sticky="ew", pady=(0, 15))
        PhotoLabel(header, text="直播弹幕控制台", fg=colors["text"],
                 font=("Microsoft YaHei UI", 18, "bold")).pack(side="left")
        PhotoLabel(header, text="LIVE / 语音与弹幕", fg=colors["muted"],
                 font=("Segoe UI", 9)).pack(side="left", padx=(14, 0), pady=(7, 0))
        self.status = PhotoLabel(header, text="正在扫描浏览器…", fg=colors["accent"],
                               padx=12, pady=7, font=("Microsoft YaHei UI", 9))
        self.status.pack(side="right")
        PhotoButton(header, text="浏览器扩展", command=self.show_extension_setup).pack(
            side="right", padx=(0, 8))
        PhotoButton(header, text="语音设置", command=self.show_api_settings).pack(
            side="right", padx=(0, 8))

        rooms_card = tk.Frame(shell, bg=colors["surface"], bd=0, highlightthickness=0)
        rooms_card.grid(row=1, column=0, sticky="nsew")
        rooms_card.grid_columnconfigure(0, weight=1)
        rooms_card.grid_rowconfigure(1, weight=1)
        rooms_header = tk.Frame(rooms_card, bg=colors["surface"], padx=10, pady=10)
        rooms_header.grid(row=0, column=0, sticky="ew")
        PhotoLabel(rooms_header, text="直播间", fg=colors["text"],
                 font=("Microsoft YaHei UI", 11, "bold")).pack(side="left")
        self.target_mode = tk.StringVar(value="manual")
        for value, label in (("manual", "手动选择"), ("auto", "自动跟随")):
            ModeButton(rooms_header, text=label, variable=self.target_mode, value=value,
                       command=self._change_target_mode, padx=14, pady=6).pack(side="left", padx=(8, 0))
        PhotoButton(rooms_header, text="刷新房间", command=self.refresh_rooms, pady=6).pack(side="right")

        table_frame = tk.Frame(rooms_card, bg=colors["surface"], padx=5, pady=0)
        table_frame.grid(row=1, column=0, sticky="nsew")
        columns = ("platform", "room", "title", "ready", "url")
        self.table = RoomTable(table_frame, columns=columns, height=5)
        headings = {"platform": "平台", "room": "房间", "title": "页面标题", "ready": "状态", "url": "地址"}
        widths = {"platform": 80, "room": 110, "title": 260, "ready": 105, "url": 340}
        for column in columns:
            self.table.heading(column, text=headings[column])
            self.table.column(column, width=widths[column], anchor="w", minwidth=70,
                              stretch=column in ("title", "url"))
        self.table.bind("<<TreeviewSelect>>", self._select_room)
        self.table.bind("<ButtonRelease-1>", self._manual_room_choice, add="+")
        for key in ("Up", "Down", "Home", "End", "Prior", "Next", "space"):
            self.table.bind(f"<KeyRelease-{key}>", self._manual_room_choice, add="+")
        self.table.pack(fill="both", expand=True)

        action_card = tk.Frame(shell, bg=colors["surface"], bd=0, highlightthickness=0,
                               padx=10, pady=10)
        action_card.grid(row=2, column=0, sticky="ew", pady=8)
        action_card.grid_columnconfigure(0, weight=1)
        selected_row = tk.Frame(action_card, bg=colors["surface"])
        selected_row.grid(row=0, column=0, sticky="ew")
        self.selected_room_label = PhotoLabel(selected_row, text="尚未选择直播间",
                                            fg=colors["text"], font=("Microsoft YaHei UI", 11, "bold"))
        self.selected_room_label.pack(side="left")
        self.listen_indicator = PhotoLabel(selected_row, text="未监听", fg=colors["muted"],
                                          padx=10, pady=4, font=("Microsoft YaHei UI", 9))
        self.listen_indicator.pack(side="right")
        self.selected_room_hint = PhotoLabel(action_card, text="从上方列表中选择一个可发送的直播间",
                                            fg=colors["muted"],
                                            font=("Microsoft YaHei UI", 9), anchor="w")
        self.selected_room_hint.grid(row=1, column=0, sticky="ew", pady=(3, 13))

        controls = tk.Frame(action_card, bg=colors["surface"])
        controls.grid(row=2, column=0, sticky="ew")
        PhotoLabel(controls, text="发送间隔（秒）", fg=colors["muted"],
                 font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.interval_var = tk.StringVar(value="1")
        ttk.Entry(controls, textvariable=self.interval_var, width=7,
                  style="App.TEntry").pack(side="left", padx=(8, 0))
        self.listen_button = PhotoButton(controls, text="开始监听", command=self.toggle_listening,
                                       variant="primary", state="disabled", bg=colors["accent"], fg="white",
                                       activebackground=colors["accent_hover"], activeforeground="white",
                                       disabledforeground="#DCE7FB", relief="flat", bd=0,
                                       padx=24, pady=9, cursor="hand2",
                                       font=("Microsoft YaHei UI", 10, "bold"))
        self.listen_button.pack(side="right")

        message_row = tk.Frame(action_card, bg=colors["surface"])
        message_row.grid(row=3, column=0, sticky="ew", pady=(15, 0))
        PhotoLabel(message_row, text="手动弹幕", fg=colors["muted"],
                 font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.message_var = tk.StringVar()
        message_entry = ttk.Entry(message_row, textvariable=self.message_var, style="App.TEntry")
        message_entry.pack(side="left", fill="x", expand=True, padx=(15, 9))
        message_entry.bind("<Return>", lambda _: self.send_message())
        self.send_button = PhotoButton(message_row, text="发送弹幕", command=self.send_message)
        self.send_button.pack(side="right")
        log_card = tk.Frame(shell, bg=colors["surface"], bd=0, highlightthickness=0)
        log_card.grid(row=3, column=0, sticky="nsew")
        log_card.grid_columnconfigure(0, weight=1)
        log_card.grid_rowconfigure(1, weight=1)
        log_header = tk.Frame(log_card, bg=colors["surface"], padx=10, pady=8)
        log_header.grid(row=0, column=0, sticky="ew")
        PhotoLabel(log_header, text="运行日志", fg=colors["text"],
                 font=("Microsoft YaHei UI", 11, "bold")).pack(side="left")
        PhotoLabel(log_header, text="识别内容与发送结果实时显示",
                 fg=colors["muted"], font=("Microsoft YaHei UI", 9)).pack(side="left", padx=(12, 0))
        PhotoButton(log_header, text="复制日志", command=lambda: self.detail.copy_all(),
                    pady=4, padx=12).pack(side="right")
        log_frame = tk.Frame(log_card, bg=colors["surface"], padx=5, pady=0)
        log_frame.grid(row=1, column=0, sticky="nsew")
        self.detail = ActivityLog(log_frame)
        self.detail.pack(fill="both", expand=True)

        self.root.bind("<Destroy>", self._window_destroyed, add="+")
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _window_destroyed(self, event):
        if event.widget == self.root:
            # No polling or image-render callbacks should outlive this window.
            for job in self.root.tk.call("after", "info"):
                self.root.after_cancel(job)
            # Release Tk-owned resources on the UI thread, even if a browser
            # worker is the last owner of the Python panel object.
            for name, value in tuple(vars(self).items()):
                if isinstance(value, tk.Variable):
                    setattr(self, name, None)

    def show_api_settings(self):
        try:
            config = read_settings_file()
            initial_error = ""
        except VoiceError as exc:
            config = {}
            initial_error = str(exc)
        dialog = tk.Toplevel(self.root)
        dialog.withdraw()
        dialog.title("语音识别设置")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)

        ttk.Label(frame, text="语音识别", font=("Microsoft YaHei UI", 13, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 5))
        ttk.Label(frame, text="配置仅保存在本机；下次开始监听时生效。",
                  foreground="#687586").grid(row=1, column=0, sticky="w", pady=(0, 16))
        providers = {"本地 SenseVoiceSmall INT8（离线 CPU）": "sensevoice",
                     "阿里云百炼（联网）": "dashscope"}
        selected = config.get("voice_provider", DEFAULT_PROVIDER)
        provider_var = tk.StringVar(value=next(
            (label for label, value in providers.items() if value == selected),
            "阿里云百炼（联网）"))
        provider_box = ttk.Combobox(frame, textvariable=provider_var,
                                     values=list(providers), state="readonly", width=55)
        provider_box.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        local_frame = ttk.Frame(frame)
        local_frame.grid(row=3, column=0, sticky="ew")
        local_frame.columnconfigure(0, weight=1)
        ttk.Label(local_frame, text="模型目录（包含 model.int8.onnx 和 tokens.txt）").grid(
            row=0, column=0, columnspan=2, sticky="w")
        path_var = tk.StringVar(value=config.get("local_model_dir", str(default_local_model_dir())))
        path_entry = ttk.Entry(local_frame, textvariable=path_var, width=55)
        path_entry.grid(row=1, column=0, sticky="ew", pady=(5, 12))

        def browse_model():
            folder = filedialog.askdirectory(parent=dialog, title="选择 SenseVoice 模型目录")
            if folder:
                path_var.set(folder)

        browse_button = ttk.Button(local_frame, text="浏览…", command=browse_model)
        browse_button.grid(row=1, column=1, padx=(8, 0), pady=(5, 12))
        ttk.Label(local_frame, text="识别语言（auto 自动检测；zh 中文；yue 粤语）").grid(
            row=2, column=0, columnspan=2, sticky="w")
        language_var = tk.StringVar(value=config.get("local_language", "auto"))
        language_box = ttk.Combobox(local_frame, textvariable=language_var, state="readonly",
                                    values=("auto", "zh", "en", "ja", "ko", "yue"))
        language_box.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(5, 12))
        ttk.Label(local_frame, text="音量门限（dBFS，默认 -42；越低越容易收音）").grid(
            row=4, column=0, columnspan=2, sticky="w")
        threshold_var = tk.StringVar(value=str(config.get("local_threshold_db", -42)))
        threshold_entry = ttk.Spinbox(local_frame, from_=-90, to=-10, textvariable=threshold_var)
        threshold_entry.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(5, 12))
        ttk.Label(local_frame, text="直接读取本机模型，无需 API Key，音频不上传。",
                  foreground="#687586").grid(row=6, column=0, columnspan=2, sticky="w", pady=(0, 8))

        cloud_frame = ttk.Frame(frame)
        cloud_frame.grid(row=3, column=0, sticky="ew")
        cloud_frame.columnconfigure(0, weight=1)
        ttk.Label(cloud_frame, text="DashScope API Key").grid(row=2, column=0, sticky="w")
        key_var = tk.StringVar(value=config.get("dashscope_api_key", ""))
        key_entry = ttk.Entry(cloud_frame, textvariable=key_var, show="*", width=55)
        key_entry.grid(row=3, column=0, sticky="ew", pady=(5, 3))
        show_key = tk.BooleanVar(value=False)
        ttk.Checkbutton(cloud_frame, text="显示 Key", variable=show_key,
                        command=lambda: key_entry.configure(show="" if show_key.get() else "*")).grid(
                            row=4, column=0, sticky="w", pady=(0, 12))
        ttk.Label(cloud_frame, text="识别模型").grid(row=5, column=0, sticky="w")
        model_var = tk.StringVar(value=DEFAULT_MODEL)
        ttk.Entry(cloud_frame, textvariable=model_var, state="readonly").grid(
            row=6, column=0, sticky="ew", pady=(5, 12))
        ttk.Label(cloud_frame, text="WebSocket 地址").grid(row=7, column=0, sticky="w")
        url_var = tk.StringVar(value=config.get("websocket_url", DEFAULT_WS_URL))
        ttk.Entry(cloud_frame, textvariable=url_var).grid(row=8, column=0, sticky="ew", pady=(5, 12))
        if os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("DASHSCOPE_WEBSOCKET_URL"):
            ttk.Label(cloud_frame, text="检测到环境变量；百炼模式下环境变量会优先于窗口配置。",
                      foreground="#987339").grid(row=9, column=0, sticky="w", pady=(0, 8))
        error_var = tk.StringVar(value=initial_error)
        ttk.Label(frame, textvariable=error_var, foreground="#B24C5D", wraplength=480).grid(
            row=10, column=0, sticky="ew")
        buttons = ttk.Frame(frame)
        buttons.grid(row=11, column=0, sticky="e", pady=(16, 0))

        install_frame = ttk.Frame(local_frame)
        install_frame.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(4, 8))
        install_status = tk.StringVar(value=(
            f"首次安装联网下载约 {MODEL_BYTES / 1024 / 1024:.1f} MiB；安装后可离线识别。"))
        install_progress = ttk.Progressbar(local_frame, mode="determinate", maximum=MODEL_BYTES)
        install_progress.grid(row=8, column=0, columnspan=2, sticky="ew")
        ttk.Label(local_frame, textvariable=install_status, wraplength=480,
                  foreground="#687586").grid(row=9, column=0, columnspan=2, sticky="w", pady=(5, 0))
        ttk.Label(local_frame, text="下载源：魔搭优先，失败后自动切换 Hugging Face。",
                  foreground="#687586").grid(row=10, column=0, columnspan=2, sticky="w", pady=(4, 0))
        install_events = queue.Queue()
        install_cancel = threading.Event()
        installing = False
        install_timer = None
        install_options = {}

        def set_installing(value):
            nonlocal installing
            installing = value
            for widget in (path_entry, browse_button, threshold_entry, install_button, save_button):
                widget.configure(state="disabled" if value else "normal")
            for widget in (provider_box, language_box):
                widget.configure(state="disabled" if value else "readonly")
            cancel_install_button.configure(state="normal" if value else "disabled")

        def poll_install():
            nonlocal install_timer
            install_timer = None
            try:
                while True:
                    kind, value = install_events.get_nowait()
                    if kind == "progress":
                        done, total, detail = value
                        install_progress.configure(maximum=total, value=done)
                        install_status.set(f"{detail}  {done / 1024 / 1024:.1f} / "
                                           f"{total / 1024 / 1024:.1f} MiB")
                        continue
                    set_installing(False)
                    if kind == "done":
                        if install_cancel.is_set():
                            install_status.set("已取消自动配置；下载完成的模型保留在本机。")
                            continue
                        path_var.set(str(value))
                        try:
                            save_settings(install_options["key"], install_options["url"],
                                          provider="sensevoice", local_model_dir=str(value),
                                          local_language=install_options["language"],
                                          local_threshold_db=install_options["threshold"])
                        except (VoiceError, OSError) as exc:
                            install_status.set("模型已安装；请点击“保存配置”重试保存。")
                            error_var.set(str(exc))
                        else:
                            install_status.set("模型已安装并自动保存配置；下次开始监听时生效。")
                            self._append_log(f"本地语音模型已安装：{value}", "模型")
                    elif isinstance(value, ModelInstallCancelled):
                        install_status.set(str(value))
                    else:
                        install_status.set("安装失败，可重新点击“一键安装模型”重试。")
                        error_var.set(str(value))
            except queue.Empty:
                pass
            if installing:
                install_timer = dialog.after(100, poll_install)

        def start_install():
            nonlocal install_timer
            if installing:
                return
            try:
                threshold = float(threshold_var.get())
                if not -90 <= threshold <= -10:
                    raise ValueError("音量门限必须在 -90 到 -10 dBFS 之间。")
            except ValueError as exc:
                error_var.set(str(exc))
                return
            install_options.update(key=key_var.get(), url=url_var.get(),
                                   language=language_var.get(), threshold=threshold)
            install_cancel.clear()
            error_var.set("")
            install_progress.configure(value=0)
            install_status.set("正在准备安装并校验已有文件…")
            set_installing(True)

            def worker():
                try:
                    folder = install_model(
                        managed_model_dir(), cancel=install_cancel,
                        on_progress=lambda *event: install_events.put(("progress", event)))
                    install_events.put(("done", folder))
                except Exception as exc:
                    install_events.put(("error", exc))

            threading.Thread(target=worker, daemon=True).start()
            install_timer = dialog.after(100, poll_install)

        def cancel_install():
            install_cancel.set()
            install_status.set("正在取消下载…")
            cancel_install_button.configure(state="disabled")

        def dialog_destroyed(event):
            nonlocal provider_var, path_var, language_var, threshold_var, key_var, url_var
            nonlocal model_var, show_key, error_var, install_status
            if event.widget == dialog:
                install_cancel.set()
                if install_timer is not None:
                    dialog.after_cancel(install_timer)
                # Worker callbacks keep closure cells alive until they finish.
                # Destroy dialog variables here, on Tk's own thread.
                provider_var = path_var = language_var = threshold_var = None
                key_var = url_var = model_var = show_key = error_var = install_status = None

        dialog.bind("<Destroy>", dialog_destroyed, add="+")
        install_button = ttk.Button(install_frame, text="一键安装模型", command=start_install)
        install_button.pack(side="left")
        cancel_install_button = ttk.Button(install_frame, text="取消下载", command=cancel_install,
                                          state="disabled")
        cancel_install_button.pack(side="left", padx=(8, 0))

        def save():
            try:
                provider = providers[provider_var.get()]
                save_settings(key_var.get(), url_var.get(), provider=provider,
                              local_model_dir=path_var.get(), local_language=language_var.get(),
                              local_threshold_db=float(threshold_var.get()) if provider == "sensevoice" else None)
            except (VoiceError, ValueError) as exc:
                error_var.set(str(exc))
                return
            self._append_log(f"{provider_var.get()}配置已保存；下次开始监听时生效。", "配置")
            dialog.destroy()

        def update_provider(_event=None):
            local = providers[provider_var.get()] == "sensevoice"
            (cloud_frame if local else local_frame).grid_remove()
            (local_frame if local else cloud_frame).grid()

        provider_box.bind("<<ComboboxSelected>>", update_provider)
        update_provider()
        ttk.Button(buttons, text="取消", command=dialog.destroy,
                   style="App.TButton").pack(side="left", padx=(0, 8))
        save_button = ttk.Button(buttons, text="保存配置", command=save, style="App.TButton")
        save_button.pack(side="left")
        dialog.bind("<Escape>", lambda _: dialog.destroy())
        self._show_dialog(dialog)
        provider_box.focus_set()

    def show_extension_setup(self):
        from windows_extension_setup import open_extensions_page, prepare_extension

        try:
            folder = prepare_extension()
        except OSError as exc:
            self._append_log(str(exc), "扩展准备失败")
            return
        dialog = tk.Toplevel(self.root)
        dialog.withdraw()
        dialog.title("安装浏览器扩展")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text="连接已打开的直播页面",
                  font=("Microsoft YaHei UI", 13, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 8))
        ttk.Label(frame, text="扩展已包含在应用中。每个使用的浏览器只需安装一次。",
                  foreground="#687586").grid(row=1, column=0, sticky="w", pady=(0, 16))
        ttk.Label(frame, text="1. 打开 Edge 或 Chrome 的扩展管理页。\n"
                              "2. 开启“开发者模式”，点击“加载解压缩的扩展程序”。\n"
                              "3. 选择下面的扩展目录，保持扩展启用。",
                  justify="left").grid(row=2, column=0, sticky="w", pady=(0, 14))
        ttk.Label(frame, text="扩展目录").grid(row=3, column=0, sticky="w")
        folder_row = ttk.Frame(frame)
        folder_row.grid(row=4, column=0, sticky="ew", pady=(5, 12))
        folder_entry = ttk.Entry(folder_row, width=55)
        folder_entry.insert(0, str(folder))
        folder_entry.configure(state="readonly")
        folder_entry.pack(side="left", fill="x", expand=True)

        def copy_folder():
            dialog.clipboard_clear()
            dialog.clipboard_append(str(folder))
            status_var.set("扩展目录已复制。")

        ttk.Button(folder_row, text="复制路径", command=copy_folder,
                   style="App.TButton").pack(side="left", padx=(8, 0))
        browser_row = ttk.Frame(frame)
        browser_row.grid(row=5, column=0, sticky="w")
        status_var = tk.StringVar()

        def launch(browser):
            try:
                open_extensions_page(browser)
                os.startfile(folder)
            except OSError as exc:
                status_var.set(str(exc))

        ttk.Button(browser_row, text="打开 Edge 扩展页", command=lambda: launch("edge"),
                   style="App.TButton").pack(side="left", padx=(0, 8))
        ttk.Button(browser_row, text="打开 Chrome 扩展页", command=lambda: launch("chrome"),
                   style="App.TButton").pack(side="left")
        ttk.Label(frame, textvariable=status_var, foreground="#B24C5D",
                  wraplength=500).grid(row=6, column=0, sticky="ew", pady=(12, 0))
        ttk.Label(frame, text="选择目录时可能不显示文件，选中上述文件夹即可。\n"
                              "浏览器要求你在扩展页确认安装；完成后应用会自动发现直播间。",
                  foreground="#687586").grid(row=7, column=0, sticky="w", pady=(8, 0))
        dialog.bind("<Escape>", lambda _: dialog.destroy())
        self._show_dialog(dialog)

    def _show_dialog(self, dialog):
        dialog.update_idletasks()
        left = self.root.winfo_rootx() + (self.root.winfo_width() - dialog.winfo_reqwidth()) // 2
        top = self.root.winfo_rooty() + (self.root.winfo_height() - dialog.winfo_reqheight()) // 2
        dialog.geometry(f"+{max(0, left)}+{max(0, top)}")
        dialog.deiconify()
        dialog.grab_set()

    def _update_room_summary(self):
        room = self._selected()
        if room:
            self.selected_room_label.configure(text=f"{room.platform}  ·  房间 {room.room_number}")
            description = (room.title or room.url) if room.ready else (room.reason or "页面尚未准备好发送")
            if self._auto_mode() and self.auto_hint:
                description = self.auto_hint + " · " + description
            self.selected_room_hint.configure(
                text=description[:100] + ("…" if len(description) > 100 else ""))
        else:
            self.selected_room_label.configure(text="自动跟随：等待直播间" if self._auto_mode() else "尚未选择直播间")
            self.selected_room_hint.configure(text=self.auto_hint if self._auto_mode()
                                               else "从上方列表中选择一个可发送的直播间")
        if self.listening:
            self.listen_indicator.configure(text="● 监听中", fg="#347A61")
        elif self.voice:
            self.listen_indicator.configure(text="● 启动中", fg="#3B74CD")
        elif self.auto_listen_requested:
            self.listen_indicator.configure(text="● 等待直播间", fg="#987339")
        else:
            self.listen_indicator.configure(text="未监听", fg="#687586")
        running = bool(self.voice or self.auto_listen_requested)
        self.listen_button.configure(bg="#CC6670" if running else "#3B74CD",
                                     text="停止监听" if running else "开始监听",
                                     state="normal" if running or self._auto_mode() or (room and room.ready)
                                     else "disabled")

    def _auto_mode(self):
        return hasattr(self, "target_mode") and self.target_mode.get() == "auto"

    def _change_target_mode(self):
        self.auto_follow_generation += 1
        if self._auto_mode():
            self.auto_listen_requested = bool(self.voice or self.auto_listen_requested)
            if self.voice:
                self.stop_listening("已启用自动跟随，正在确认当前直播页。", keep_auto=True)
            self.selected_key = None
            self.auto_target_identity = None
            self.auto_hint = "正在识别最近使用的浏览器活动页…"
            self._sync_table_selection()
            self._append_log("已启用自动跟随；切换直播页时自动更换目标。", "选择模式")
            self._request_auto_room()
        else:
            self.auto_listen_requested = False
            self._append_log("已切换为手动选择，当前目标保持不变。", "选择模式")
        self._update_room_summary()

    def _auto_follow_timer(self):
        self._request_auto_room()
        self.root.after(500, self._auto_follow_timer)

    def _request_auto_room(self):
        if not self._auto_mode() or self.auto_follow_busy:
            return
        self.auto_follow_busy = True
        generation = self.auto_follow_generation

        def worker():
            try:
                room, hint = self.browser.viewing_room()
                self.jobs.put(("auto-room", (generation, room, hint), None))
            except Exception as exc:
                self.jobs.put(("auto-room", (generation, None, "读取浏览器活动页失败。"), exc))

        threading.Thread(target=worker, daemon=True).start()

    def _sync_table_selection(self):
        self.rendering_rooms = True
        try:
            selected = self.table.selection()
            if selected:
                self.table.selection_remove(*selected)
            for index, room in enumerate(self.rooms):
                if room.key == self.selected_key:
                    self.table.selection_set(str(index))
                    self.table.focus(str(index))
                    self.table.see(str(index))
                    break
        finally:
            self.rendering_rooms = False

    def _apply_auto_room(self, room, hint):
        identity = (room.key, room.platform, room.room_number) if room else None
        changed = identity != self.auto_target_identity
        self.auto_hint = hint
        if self.voice and (changed or not room or not room.ready):
            self.stop_listening("自动跟随目标变化或暂不可用；已清空旧目标的待发送语音。", keep_auto=True)
        self.auto_target_identity = identity
        self.selected_key = room.key if room else None
        if room:
            index = next((i for i, item in enumerate(self.rooms) if item.key == room.key), None)
            if index is None:
                self._render_rooms([*self.rooms, room], None)
            elif self.rooms[index] != room:
                rooms = list(self.rooms)
                rooms[index] = room
                self._render_rooms(rooms, None)
            if changed:
                self._append_log(f"已跟随 {room.platform} 房间 {room.room_number}。", "自动选择")
        elif changed:
            self._append_log(hint, "自动跟随暂停")
        if changed:
            self._sync_table_selection()
        if self.auto_listen_requested and room and room.ready and not self.voice:
            self.start_listening()
        self._update_room_summary()

    def _append_log(self, text, category="信息"):
        stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        line = f"[{stamp}] {category}：{str(text).strip()}\n"
        tag = ("error" if "失败" in category or "未发送" in category else
               "success" if "已触发" in category else
               "recognized" if category == "识别" else "")
        self.detail.append(line, tag)

    def _scan_notice(self, text):
        if text != self.last_scan_notice:
            self.last_scan_notice = text
            self._append_log(text)

    def _selected(self):
        if self.selected_key is None:
            return None
        return next((room for room in self.rooms if room.key == self.selected_key), None)

    def _refresh_timer(self):
        self.refresh_rooms(show_status=False)
        self.root.after(5000, self._refresh_timer)

    def refresh_rooms(self, show_status=True):
        if self.refreshing:
            return
        self.refreshing = True
        if show_status:
            self.status.configure(text="正在扫描浏览器…")

        def worker():
            try:
                result = self.browser.rooms()
                self.jobs.put(("rooms", result, self.browser.last_error))
            except Exception as exc:
                self.jobs.put(("rooms", [], exc))

        threading.Thread(target=worker, daemon=True).start()

    def _render_rooms(self, rooms, error):
        self.refreshing = False
        self.rooms = rooms
        selected = self.selected_key
        if self.listening and not self._auto_mode():
            if any(room.key == self.listening_target_key and room.ready for room in rooms):
                self.target_missing_since = None
            elif self.target_missing_since is None:
                self.target_missing_since = time.monotonic()
                self._append_log("监听目标暂不可发送；等待直播页恢复。", "等待页面")
            elif time.monotonic() - self.target_missing_since >= MISSING_TARGET_GRACE_SECONDS:
                self.stop_listening("监听的直播标签页持续不可用，监听已停止。")
        self.rendering_rooms = True
        for item in self.table.get_children():
            self.table.delete(item)
        for index, room in enumerate(rooms):
            state = "可发送" if room.ready else (room.reason or "未登录/控件未加载")
            self.table.insert("", "end", iid=str(index), values=(
                room.platform, room.room_number, room.title or "(无标题)", state, room.url,
            ))
        if selected:
            for index, room in enumerate(rooms):
                if room.key == selected:
                    self.table.selection_set(str(index))
                    self.table.focus(str(index))
                    break
        self.rendering_rooms = False
        if selected and not any(room.key == selected for room in rooms) and not self.listening:
            self.selected_key = None
        if error:
            self.status.configure(text="浏览器扫描失败")
            self._scan_notice(str(error))
        elif not rooms:
            self.status.configure(text="未发现直播页面")
            if self.browser.extension_connected:
                self._scan_notice("浏览器扩展已连接；当前没有发现抖音、斗鱼或 B 站直播页。")
            elif self.browser.extension_error:
                self._scan_notice("浏览器扩展连接服务启动失败：" + self.browser.extension_error)
            else:
                self._scan_notice("未发现直播页。点击顶部“安装浏览器扩展”完成首次设置后，应用会自动列出所有已打开的直播标签页。")
        else:
            self.last_scan_notice = None
            prefix = "监听中 · " if self.listening else ""
            mode = ("扩展已连接" if any(room.source == "extension" for room in rooms)
                    else "后台连接" if any(room.source == "cdp" for room in rooms)
                    else "仅当前标签页")
            self.status.configure(text=f"{prefix}{mode} · {len(rooms)} 个直播页面")
        selected_room = self._selected()
        self.listen_button.configure(state="normal" if self.voice or (selected_room and selected_room.ready) else "disabled")
        self._update_room_summary()

    def _select_room(self, _event=None):
        if self.rendering_rooms or self._auto_mode():
            return
        selection = self.table.selection()
        if not selection:
            if self._auto_mode():
                return
            self.selected_key = None
            self.listen_button.configure(state="normal" if self.voice else "disabled")
            self._update_room_summary()
            return
        index = int(selection[0])
        if index >= len(self.rooms):
            return
        room = self.rooms[index]
        previous_key = self.selected_key
        if previous_key == room.key:
            return
        self.selected_key = room.key
        self.listen_button.configure(state="normal" if room.ready or self.voice else "disabled")
        if self.voice and self.listening_target_key != room.key and previous_key != room.key:
            self.stop_listening("已切换直播间，已停止原目标的语音监听。")
        self._update_room_summary()
        self._append_log(
            f"已选择 {room.platform} 房间 {room.room_number}；"
            f"{'可发送' if room.ready else room.reason or '暂不可发送'}"
        )

    def _manual_room_choice(self, _event=None):
        if self.rendering_rooms:
            return
        selection = self.table.selection()
        if not selection:
            return
        index = int(selection[0])
        if index >= len(self.rooms) or self.rooms[index].key == self.selected_key:
            return
        if self._auto_mode():
            self.target_mode.set("manual")
            self._change_target_mode()
        self._select_room()

    def _drain_jobs(self):
        try:
            while True:
                kind, value, error = self.jobs.get_nowait()
                if kind == "rooms":
                    self._render_rooms(value, error)
                elif kind == "auto-room":
                    self.auto_follow_busy = False
                    generation, room, hint = value
                    if self._auto_mode() and generation == self.auto_follow_generation:
                        self._apply_auto_room(room, str(error) if error else hint)
                elif kind == "send":
                    message, result = value
                    self._finish_send(message, result, error)
                elif kind == "voice-start":
                    session, started = value
                    if session == self.voice_session:
                        self._finish_voice_start(started, error)
                elif kind == "voice":
                    session, sentence = value
                    if session == self.voice_session:
                        self._send_voice_sentence(sentence)
                elif kind == "voice-send":
                    session, message, result = value
                    if session == self.voice_session:
                        self._finish_voice_send(message, result, error)
                    else:
                        self._append_log(
                            f"{message}；{error or json_message(result)}",
                            "已停止会话的发送结果",
                        )
        except queue.Empty:
            pass
        if self.listening and self.voice and self.voice.error:
            self.stop_listening(str(self.voice.error))
        self.root.after(100, self._drain_jobs)

    def _finish_send(self, message, result, error):
        self.send_button.configure(state="normal")
        if error:
            self.status.configure(text="发送失败")
            self._append_log(f"{message}；{error}", "发送失败")
        else:
            self.status.configure(text="已触发网页发送")
            self._append_log(f"{message}；{json_message(result)}", "网页发送已触发")

    def send_message(self):
        room = self._selected()
        message = self.message_var.get().strip()
        if not room:
            self._append_log("请先选择直播间。")
            return
        if not room.ready:
            self._append_log("当前直播间尚未具备发送条件：" + (room.reason or "请等待页面加载或登录。"))
            return
        if not message:
            self._append_log("请输入弹幕内容。")
            return
        self.send_button.configure(state="disabled")
        self._append_log(message, "手动发送中")
        follow_active = self._auto_mode()

        def worker():
            try:
                result = (self.browser.send(room, message, follow_active=True) if follow_active
                          else self.browser.send(room, message))
                self.jobs.put(("send", (message, result), None))
            except Exception as exc:
                self.jobs.put(("send", (message, None), exc))

        threading.Thread(target=worker, daemon=True).start()

    def toggle_listening(self):
        if self.voice or self.auto_listen_requested:
            self.stop_listening()
        else:
            self.start_listening()

    def start_listening(self):
        room = self._selected()
        if (not room or not room.ready) and not self._auto_mode():
            self._append_log("请先选择一个可发送的直播间。")
            return
        try:
            interval = float(self.interval_var.get())
            if not math.isfinite(interval) or interval < 0:
                raise ValueError
        except ValueError:
            self._append_log("发送间隔必须是大于或等于 0 的数字。")
            return
        self.interval = interval
        if self._auto_mode():
            self.auto_listen_requested = True
            if not room or not room.ready:
                self.status.configure(text="自动监听：等待可发送的活动直播页…")
                self._update_room_summary()
                return
        self.stop_voice = threading.Event()
        self.voice_session += 1
        session = self.voice_session
        stop_event = self.stop_voice
        self.voice = VoiceStream(silence_ms=500)
        voice = self.voice
        self.listening_target_key = room.key
        self.target_missing_since = None
        self.voice_pending.clear()
        self.voice_send_busy = False
        self.voice_waiting_for_room = False
        self.voice_inflight = None
        self.last_sent = 0.0
        self.listen_button.configure(text="停止监听", state="normal")
        self.status.configure(text="正在启动语音监听…")
        self._update_room_summary()
        self._append_log(f"{room.platform} 房间 {room.room_number}，发送间隔 {interval:g} 秒", "启动监听")

        def worker():
            try:
                voice.start()
                if stop_event.is_set():
                    return
                self.jobs.put(("voice-start", (session, True), None))
                while not stop_event.is_set():
                    sentence = voice.get_sentence(timeout=0.25)
                    if sentence:
                        self.jobs.put(("voice", (session, sentence), None))
            except Exception as exc:
                if not stop_event.is_set():
                    self.jobs.put(("voice-start", (session, None), exc))
            finally:
                voice.close()

        self.voice_thread = threading.Thread(target=worker, daemon=True)
        self.voice_thread.start()

    def _finish_voice_start(self, started, error):
        if error or not started:
            self.stop_listening(str(error or "语音监听启动失败"))
            return
        self.listening = True
        self.status.configure(text="监听中")
        self._update_room_summary()
        self._append_log(f"{self.voice.backend_label}已启动，等待识别完整句子。", "监听")

    def _send_voice_sentence(self, sentence):
        if not self.listening:
            return
        sentence = str(sentence).strip()
        if not sentence:
            return
        self._append_log(sentence, "识别")
        if self._auto_mode():
            current, _ = self.browser.viewing_room(refresh_native=False)
            selected = self._selected()
            if (not current or not selected or (current.key, current.room_number)
                    != (selected.key, selected.room_number)):
                self._append_log(sentence, "未发送（活动直播页已变化）")
                self._request_auto_room()
                return
        if len(self.voice_pending) >= MAX_VOICE_QUEUE:
            self._append_log(sentence, "未发送（等待队列已满）")
            return
        self.voice_pending.append(sentence)
        if self.voice_send_busy or self.voice_send_timer is not None:
            self._append_log(f"{sentence}；前方还有 {len(self.voice_pending) - 1} 条", "排队发送")
        self._pump_voice_send()

    def _pump_voice_send(self):
        if not self.listening or self.voice_send_busy or not self.voice_pending:
            return
        remaining = self.interval - (time.monotonic() - self.last_sent)
        if remaining > 0:
            if self.voice_send_timer is None:
                self._append_log(f"{len(self.voice_pending)} 条待发送；约 {remaining:.0f} 秒后尝试下一条", "等待发送")
                self.voice_send_timer = self.root.after(max(50, int(remaining * 1000)), self._voice_timer_ready)
            return
        room = next((item for item in self.rooms if item.key == self.listening_target_key), None)
        if not room or not room.ready:
            if not self.voice_waiting_for_room:
                self._append_log(f"目标直播页暂不可发送，保留 {len(self.voice_pending)} 条等待内容。", "等待页面")
                self.voice_waiting_for_room = True
            if self.voice_send_timer is None:
                self.voice_send_timer = self.root.after(1000, self._voice_timer_ready)
            return
        self.voice_waiting_for_room = False
        message = self.voice_pending.popleft()
        self.voice_send_busy = True
        self.voice_inflight = message
        self.last_sent = time.monotonic()
        session = self.voice_session
        self._append_log(message, "语音发送中")
        follow_active = self._auto_mode()

        def worker():
            try:
                result = (self.browser.send(room, message, follow_active=True) if follow_active
                          else self.browser.send(room, message))
                self.jobs.put(("voice-send", (session, message, result), None))
            except Exception as exc:
                self.jobs.put(("voice-send", (session, message, None), exc))

        threading.Thread(target=worker, daemon=True).start()

    def _voice_timer_ready(self):
        self.voice_send_timer = None
        self._pump_voice_send()

    def _finish_voice_send(self, message, result, error):
        self.voice_send_busy = False
        self.voice_inflight = None
        if error:
            self._append_log(f"{message}；{error}", "语音发送失败")
        else:
            self._append_log(f"{message}；{json_message(result)}", "语音网页发送已触发")
        self._pump_voice_send()

    def stop_listening(self, reason="", *, keep_auto=False):
        was_listening = self.voice is not None
        self.stop_voice.set()
        if not keep_auto:
            self.auto_listen_requested = False
        self.voice_session += 1
        if self.voice:
            self.voice.close()
        self.voice = None
        self.listening = False
        self.listening_target_key = None
        self.target_missing_since = None
        for message in self.voice_pending:
            self._append_log(message, "未发送（监听已停止）")
        self.voice_pending.clear()
        if self.voice_inflight is not None:
            self._append_log(self.voice_inflight, "发送中（等待网页结果）")
        self.voice_inflight = None
        self.voice_send_busy = False
        self.voice_waiting_for_room = False
        if self.voice_send_timer is not None:
            self.root.after_cancel(self.voice_send_timer)
            self.voice_send_timer = None
        selected = self._selected()
        self.listen_button.configure(text="开始监听", state="normal" if selected and selected.ready else "disabled")
        self.status.configure(text="未监听")
        self._update_room_summary()
        if reason:
            self._append_log(reason, "监听已停止")
        elif was_listening:
            self._append_log("语音监听已停止。", "监听")

    def close(self):
        self.stop_listening()
        if self.browser.extension_bridge:
            self.browser.extension_bridge.close()
        self.root.destroy()


def json_message(result):
    if not isinstance(result, dict):
        return str(result)
    return "发送结果：" + str(result.get("confirmation", result.get("state", "done")))


def main():
    if "--self-check" in sys.argv:
        import argparse
        from portable_check import run_check
        parser = argparse.ArgumentParser()
        parser.add_argument("--self-check", required=True)
        parser.add_argument("--self-check-audio")
        options = parser.parse_args()
        raise SystemExit(run_check(options.self_check, options.self_check_audio))
    if sys.platform == "win32":
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    root = tk.Tk()
    root.withdraw()
    WindowsControlPanel(root)
    root.update_idletasks()
    root.deiconify()
    root.mainloop()


if __name__ == "__main__":
    main()
