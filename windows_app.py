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
from pathlib import Path
from tkinter import ttk

from voice import (DEFAULT_MODEL, DEFAULT_WS_URL, VoiceError, VoiceStream,
                   read_settings_file, save_settings)
from windows_browser import WindowsBrowser

MAX_VOICE_QUEUE = 100
MISSING_TARGET_GRACE_SECONDS = 30
BACKGROUND_IMAGE = (Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
                    / "assets" / "120131650_p0_master1200.jpg")


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
        self.jobs = queue.Queue()
        self.last_scan_notice = None
        self._build()
        self._draw_background(width, height)
        self.root.after(150, self._make_controls_translucent)
        self.root.after(100, self._drain_jobs)
        self.root.after(200, self.refresh_rooms)
        self.root.after(5000, self._refresh_timer)

    def _build(self):
        colors = {
            "background": "#F3F6FA", "surface": "#FFFFFF", "text": "#17243A",
            "muted": "#66758C", "border": "#DFE6EF", "accent": "#2864DC",
            "accent_hover": "#1E55C2", "success": "#18835A", "error": "#BF4242",
        }
        self.root.configure(bg=colors["background"])
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("App.Treeview", background=colors["surface"], fieldbackground=colors["surface"],
                        foreground=colors["text"], rowheight=30, borderwidth=0,
                        font=("Microsoft YaHei UI", 9))
        style.configure("App.Treeview.Heading", background="#F7F9FC", foreground=colors["muted"],
                        relief="flat", padding=(8, 9), font=("Microsoft YaHei UI", 9, "bold"))
        style.map("App.Treeview", background=[("selected", "#E4EEFF")],
                  foreground=[("selected", colors["text"])])
        style.map("App.Treeview.Heading", background=[("active", "#F0F4FA")])
        style.configure("App.TButton", padding=(12, 7), font=("Microsoft YaHei UI", 9))
        style.configure("App.TEntry", padding=7)

        try:
            from PIL import Image
            self.background_source = Image.open(BACKGROUND_IMAGE).convert("RGB")
        except (ImportError, OSError):
            self.background_source = None
        self.background_photo = None
        self.background_size = None
        self.background_job = None
        self.photo_surfaces = []
        self.surface_photos = {}
        shell = tk.Frame(self.root, bg=colors["background"], bd=0, padx=20, pady=18)
        self.background_panel = shell
        shell.pack(fill="both", expand=True)
        self.background_layer = tk.Label(shell, borderwidth=0)
        self.background_layer.place(x=0, y=0, relwidth=1, relheight=1)
        self.background_layer.lower()
        shell.grid_columnconfigure(0, weight=1)
        shell.grid_rowconfigure(1, weight=2)
        shell.grid_rowconfigure(3, weight=2)
        if self.background_source:
            shell.bind("<Configure>", self._schedule_background_resize)

        header = tk.Frame(shell, bg=colors["background"])
        self._add_photo_surface(header)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 15))
        tk.Label(header, text="直播弹幕控制台", bg=colors["background"], fg=colors["text"],
                 font=("Microsoft YaHei UI", 18, "bold")).pack(side="left")
        tk.Label(header, text="WINDOWS · 网页直播", bg=colors["background"], fg=colors["muted"],
                 font=("Segoe UI", 9)).pack(side="left", padx=(14, 0), pady=(7, 0))
        self.status = tk.Label(header, text="正在扫描浏览器…", bg="#EAF1FF", fg=colors["accent"],
                               padx=12, pady=7, font=("Microsoft YaHei UI", 9))
        self.status.pack(side="right")
        ttk.Button(header, text="安装浏览器扩展", command=self.show_extension_setup,
                   style="App.TButton").pack(side="right", padx=(0, 8))
        ttk.Button(header, text="API 设置", command=self.show_api_settings,
                   style="App.TButton").pack(side="right", padx=(0, 8))

        rooms_card = tk.Frame(shell, bg=colors["surface"], highlightbackground=colors["border"],
                              highlightthickness=1)
        self._add_photo_surface(rooms_card)
        rooms_card.grid(row=1, column=0, sticky="nsew")
        rooms_card.grid_columnconfigure(0, weight=1)
        rooms_card.grid_rowconfigure(1, weight=1)
        rooms_header = tk.Frame(rooms_card, bg=colors["surface"], padx=16, pady=13)
        self._add_photo_surface(rooms_header)
        rooms_header.grid(row=0, column=0, sticky="ew")
        tk.Label(rooms_header, text="已打开的直播间", bg=colors["surface"], fg=colors["text"],
                 font=("Microsoft YaHei UI", 11, "bold")).pack(side="left")
        tk.Label(rooms_header, text="自动发现浏览器中的直播页面", bg=colors["surface"],
                 fg=colors["muted"], font=("Microsoft YaHei UI", 9)).pack(side="left", padx=(12, 0))
        ttk.Button(rooms_header, text="刷新房间", command=self.refresh_rooms,
                   style="App.TButton").pack(side="right")

        table_frame = tk.Frame(rooms_card, bg=colors["surface"], padx=12, pady=0)
        self._add_photo_surface(table_frame)
        table_frame.grid(row=1, column=0, sticky="nsew")
        columns = ("platform", "room", "title", "ready", "url")
        self.table = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse",
                                  height=5, style="App.Treeview")
        headings = {"platform": "平台", "room": "房间", "title": "页面标题", "ready": "状态", "url": "地址"}
        widths = {"platform": 80, "room": 110, "title": 260, "ready": 105, "url": 340}
        for column in columns:
            self.table.heading(column, text=headings[column])
            self.table.column(column, width=widths[column], anchor="w", minwidth=70,
                              stretch=column in ("title", "url"))
        self.table.bind("<<TreeviewSelect>>", self._select_room)
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        tk.Frame(rooms_card, bg=colors["surface"], height=10).grid(row=2, column=0)

        action_card = tk.Frame(shell, bg=colors["surface"], highlightbackground=colors["border"],
                               highlightthickness=1, padx=16, pady=14)
        self._add_photo_surface(action_card)
        action_card.grid(row=2, column=0, sticky="ew", pady=12)
        action_card.grid_columnconfigure(0, weight=1)
        selected_row = tk.Frame(action_card, bg=colors["surface"])
        self._add_photo_surface(selected_row)
        selected_row.grid(row=0, column=0, sticky="ew")
        self.selected_room_label = tk.Label(selected_row, text="尚未选择直播间", bg=colors["surface"],
                                            fg=colors["text"], font=("Microsoft YaHei UI", 11, "bold"))
        self.selected_room_label.pack(side="left")
        self.listen_indicator = tk.Label(selected_row, text="未监听", bg="#F0F3F7", fg=colors["muted"],
                                          padx=10, pady=4, font=("Microsoft YaHei UI", 9))
        self.listen_indicator.pack(side="right")
        self.selected_room_hint = tk.Label(action_card, text="从上方列表中选择一个可发送的直播间",
                                            bg=colors["surface"], fg=colors["muted"],
                                            font=("Microsoft YaHei UI", 9), anchor="w")
        self.selected_room_hint.grid(row=1, column=0, sticky="ew", pady=(3, 13))

        controls = tk.Frame(action_card, bg=colors["surface"])
        self._add_photo_surface(controls)
        controls.grid(row=2, column=0, sticky="ew")
        tk.Label(controls, text="发送间隔（秒）", bg=colors["surface"], fg=colors["muted"],
                 font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.interval_var = tk.StringVar(value="1")
        ttk.Entry(controls, textvariable=self.interval_var, width=7,
                  style="App.TEntry").pack(side="left", padx=(8, 0))
        self.listen_button = tk.Button(controls, text="开始监听", command=self.toggle_listening,
                                       state="disabled", bg=colors["accent"], fg="white",
                                       activebackground=colors["accent_hover"], activeforeground="white",
                                       disabledforeground="#DCE7FB", relief="flat", bd=0,
                                       padx=24, pady=9, cursor="hand2",
                                       font=("Microsoft YaHei UI", 10, "bold"))
        self.listen_button.pack(side="right")

        message_row = tk.Frame(action_card, bg=colors["surface"])
        self._add_photo_surface(message_row)
        message_row.grid(row=3, column=0, sticky="ew", pady=(15, 0))
        tk.Label(message_row, text="手动弹幕", bg=colors["surface"], fg=colors["muted"],
                 font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.message_var = tk.StringVar()
        message_entry = ttk.Entry(message_row, textvariable=self.message_var, style="App.TEntry")
        message_entry.pack(side="left", fill="x", expand=True, padx=(15, 9))
        message_entry.bind("<Return>", lambda _: self.send_message())
        self.send_button = ttk.Button(message_row, text="发送弹幕", command=self.send_message,
                                      style="App.TButton")
        self.send_button.pack(side="right")
        log_card = tk.Frame(shell, bg=colors["surface"], highlightbackground=colors["border"],
                            highlightthickness=1)
        self._add_photo_surface(log_card)
        log_card.grid(row=3, column=0, sticky="nsew")
        log_card.grid_columnconfigure(0, weight=1)
        log_card.grid_rowconfigure(1, weight=1)
        log_header = tk.Frame(log_card, bg=colors["surface"], padx=16, pady=11)
        self._add_photo_surface(log_header)
        log_header.grid(row=0, column=0, sticky="ew")
        tk.Label(log_header, text="运行日志", bg=colors["surface"], fg=colors["text"],
                 font=("Microsoft YaHei UI", 11, "bold")).pack(side="left")
        tk.Label(log_header, text="识别内容与发送结果实时显示", bg=colors["surface"],
                 fg=colors["muted"], font=("Microsoft YaHei UI", 9)).pack(side="left", padx=(12, 0))
        log_frame = tk.Frame(log_card, bg=colors["surface"], padx=12, pady=0)
        self._add_photo_surface(log_frame)
        log_frame.grid(row=1, column=0, sticky="nsew")
        self.detail = tk.Text(log_frame, height=8, state="disabled", wrap="word", relief="flat",
                              bg="#F8FAFD", fg=colors["text"], selectbackground="#DCE9FF",
                              padx=10, pady=8, spacing1=3, spacing3=3,
                              font=("Consolas", 9))
        self.detail.tag_configure("success", foreground=colors["success"])
        self.detail.tag_configure("error", foreground=colors["error"])
        self.detail.tag_configure("recognized", foreground=colors["accent"])
        log_scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.detail.yview)
        self.detail.configure(yscrollcommand=log_scrollbar.set)
        self.detail.pack(side="left", fill="both", expand=True)
        log_scrollbar.pack(side="right", fill="y")
        tk.Frame(log_card, bg=colors["surface"], height=10).grid(row=2, column=0)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _add_photo_surface(self, frame):
        if self.background_source is None:
            return
        background = tk.Label(frame, borderwidth=0)
        background.place(x=0, y=0, relwidth=1, relheight=1)
        background.lower()
        self.photo_surfaces.append((frame, background))
        frame.bind("<Configure>", self._schedule_background_resize)

    def _schedule_background_resize(self, event):
        if self.background_job is not None:
            self.root.after_cancel(self.background_job)
        self.background_job = self.root.after(80, self._draw_background)

    def _draw_background(self, width=None, height=None):
        self.background_job = None
        if self.background_source is None:
            return
        width = width or self.background_panel.winfo_width()
        height = height or self.background_panel.winfo_height()
        if width < 2 or height < 2:
            return
        from PIL import Image, ImageOps, ImageTk

        if self.background_size != (width, height):
            image = ImageOps.fit(self.background_source, (width, height),
                                 method=Image.Resampling.LANCZOS, centering=(0.5, 0.4))
            image = Image.blend(image, Image.new("RGB", (width, height), "white"), 0.62)
            self.background_photo = ImageTk.PhotoImage(image, master=self.root)
            self.background_layer.configure(image=self.background_photo)
            self.background_layer.lower()
            self.background_image = image
            self.background_size = (width, height)

        origin_x = self.background_panel.winfo_rootx()
        origin_y = self.background_panel.winfo_rooty()
        for frame, background in self.photo_surfaces:
            if not frame.winfo_ismapped():
                continue
            left = frame.winfo_rootx() - origin_x
            top = frame.winfo_rooty() - origin_y
            right = min(left + frame.winfo_width(), width)
            bottom = min(top + frame.winfo_height(), height)
            if left < 0 or top < 0 or right <= left or bottom <= top:
                continue
            photo = ImageTk.PhotoImage(self.background_image.crop((left, top, right, bottom)),
                                       master=self.root)
            background.configure(image=photo)
            background.lower()
            self.surface_photos[background] = photo

    def _make_controls_translucent(self):
        if sys.platform != "win32" or self.background_source is None:
            return
        user32 = ctypes.windll.user32
        translucent_widgets = (tk.Text, tk.Entry, tk.Button, ttk.Treeview, ttk.Entry,
                               ttk.Button, ttk.Scrollbar)
        background_layers = {self.background_layer}
        background_layers.update(background for _, background in self.photo_surfaces)

        def apply(widget):
            if widget not in background_layers and isinstance(widget, (tk.Label,) + translucent_widgets):
                handle = widget.winfo_id()
                style = user32.GetWindowLongW(handle, -20)
                user32.SetWindowLongW(handle, -20, style | 0x80000)
                if isinstance(widget, tk.Label):
                    red, green, blue = (value // 256 for value in widget.winfo_rgb(widget.cget("bg")))
                    user32.SetLayeredWindowAttributes(handle, red | green << 8 | blue << 16, 0, 0x1)
                else:
                    user32.SetLayeredWindowAttributes(handle, 0, 220, 0x2)
            for child in widget.winfo_children():
                apply(child)

        apply(self.background_panel)

    def show_api_settings(self):
        try:
            config = read_settings_file()
            initial_error = ""
        except VoiceError as exc:
            config = {}
            initial_error = str(exc)
        dialog = tk.Toplevel(self.root)
        dialog.withdraw()
        dialog.title("语音识别 API 设置")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)

        ttk.Label(frame, text="百炼语音识别", font=("Microsoft YaHei UI", 13, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 5))
        ttk.Label(frame, text="配置仅保存在本机；下次开始监听时生效。",
                  foreground="#66758C").grid(row=1, column=0, sticky="w", pady=(0, 16))
        ttk.Label(frame, text="DashScope API Key").grid(row=2, column=0, sticky="w")
        key_var = tk.StringVar(value=config.get("dashscope_api_key", ""))
        key_entry = ttk.Entry(frame, textvariable=key_var, show="*", width=55)
        key_entry.grid(row=3, column=0, sticky="ew", pady=(5, 3))
        show_key = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text="显示 Key", variable=show_key,
                        command=lambda: key_entry.configure(show="" if show_key.get() else "*")).grid(
                            row=4, column=0, sticky="w", pady=(0, 12))
        ttk.Label(frame, text="识别模型").grid(row=5, column=0, sticky="w")
        model_var = tk.StringVar(value=DEFAULT_MODEL)
        ttk.Entry(frame, textvariable=model_var, state="readonly").grid(
            row=6, column=0, sticky="ew", pady=(5, 12))
        ttk.Label(frame, text="WebSocket 地址").grid(row=7, column=0, sticky="w")
        url_var = tk.StringVar(value=config.get("websocket_url", DEFAULT_WS_URL))
        ttk.Entry(frame, textvariable=url_var).grid(row=8, column=0, sticky="ew", pady=(5, 12))
        if os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("DASHSCOPE_WEBSOCKET_URL"):
            ttk.Label(frame, text="检测到环境变量；环境变量会优先于窗口配置。",
                      foreground="#A6661A").grid(row=9, column=0, sticky="w", pady=(0, 8))
        error_var = tk.StringVar(value=initial_error)
        ttk.Label(frame, textvariable=error_var, foreground="#BF4242", wraplength=480).grid(
            row=10, column=0, sticky="ew")
        buttons = ttk.Frame(frame)
        buttons.grid(row=11, column=0, sticky="e", pady=(16, 0))

        def save():
            try:
                save_settings(key_var.get(), url_var.get())
            except VoiceError as exc:
                error_var.set(str(exc))
                return
            self._append_log("语音 API 配置已保存；下次开始监听时生效。", "配置")
            dialog.destroy()

        ttk.Button(buttons, text="取消", command=dialog.destroy,
                   style="App.TButton").pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="保存配置", command=save,
                   style="App.TButton").pack(side="left")
        dialog.bind("<Escape>", lambda _: dialog.destroy())
        self._show_dialog(dialog)
        key_entry.focus_set()

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
                  foreground="#66758C").grid(row=1, column=0, sticky="w", pady=(0, 16))
        ttk.Label(frame, text="1. 打开 Edge 或 Chrome 的扩展管理页。\n"
                              "2. 开启“开发者模式”，点击“加载解压缩的扩展程序”。\n"
                              "3. 选择下面的扩展目录，保持扩展启用。",
                  justify="left").grid(row=2, column=0, sticky="w", pady=(0, 14))
        ttk.Label(frame, text="扩展目录").grid(row=3, column=0, sticky="w")
        folder_row = ttk.Frame(frame)
        folder_row.grid(row=4, column=0, sticky="ew", pady=(5, 12))
        folder_var = tk.StringVar(value=str(folder))
        ttk.Entry(folder_row, textvariable=folder_var, state="readonly", width=55).pack(
            side="left", fill="x", expand=True)

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
        ttk.Label(frame, textvariable=status_var, foreground="#BF4242",
                  wraplength=500).grid(row=6, column=0, sticky="ew", pady=(12, 0))
        ttk.Label(frame, text="浏览器要求你在扩展页确认安装；完成后应用会自动发现直播间。",
                  foreground="#66758C").grid(row=7, column=0, sticky="w", pady=(8, 0))
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
            self.selected_room_hint.configure(
                text=description[:100] + ("…" if len(description) > 100 else ""))
        else:
            self.selected_room_label.configure(text="尚未选择直播间")
            self.selected_room_hint.configure(text="从上方列表中选择一个可发送的直播间")
        if self.listening:
            self.listen_indicator.configure(text="● 监听中", bg="#E8F7EF", fg="#18835A")
        elif self.voice:
            self.listen_indicator.configure(text="● 启动中", bg="#EAF1FF", fg="#2864DC")
        else:
            self.listen_indicator.configure(text="未监听", bg="#F0F3F7", fg="#66758C")
        self.listen_button.configure(bg="#BF4242" if self.voice else "#2864DC",
                                     activebackground="#A93535" if self.voice else "#1E55C2")

    def _append_log(self, text, category="信息"):
        stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        line = f"[{stamp}] {category}：{str(text).strip()}\n"
        self.detail.configure(state="normal")
        tag = ("error" if "失败" in category or "未发送" in category else
               "success" if "已触发" in category else
               "recognized" if category == "识别" else "")
        self.detail.insert("end", line, tag)
        lines = int(self.detail.index("end-1c").split(".")[0])
        if lines > 1000:
            self.detail.delete("1.0", f"{lines - 1000}.0")
        self.detail.see("end")
        self.detail.configure(state="disabled")

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
        if self.listening:
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
        if self.rendering_rooms:
            return
        selection = self.table.selection()
        if not selection:
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
        if self.listening and self.listening_target_key != room.key and previous_key != room.key:
            self.stop_listening("已切换直播间，已停止原目标的语音监听。")
        self._update_room_summary()
        self._append_log(
            f"已选择 {room.platform} 房间 {room.room_number}；"
            f"{'可发送' if room.ready else room.reason or '暂不可发送'}"
        )

    def _drain_jobs(self):
        try:
            while True:
                kind, value, error = self.jobs.get_nowait()
                if kind == "rooms":
                    self._render_rooms(value, error)
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

        def worker():
            try:
                result = self.browser.send(room, message)
                self.jobs.put(("send", (message, result), None))
            except Exception as exc:
                self.jobs.put(("send", (message, None), exc))

        threading.Thread(target=worker, daemon=True).start()

    def toggle_listening(self):
        if self.voice:
            self.stop_listening()
        else:
            self.start_listening()

    def start_listening(self):
        room = self._selected()
        if not room or not room.ready:
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

        self.voice_thread = threading.Thread(target=worker, daemon=True)
        self.voice_thread.start()

    def _finish_voice_start(self, started, error):
        if error or not started:
            self.stop_listening(str(error or "语音监听启动失败"))
            return
        self.listening = True
        self.status.configure(text="监听中")
        self._update_room_summary()
        self._append_log("语音监听已启动，等待识别完整句子。", "监听")

    def _send_voice_sentence(self, sentence):
        if not self.listening:
            return
        sentence = str(sentence).strip()
        if not sentence:
            return
        self._append_log(sentence, "识别")
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

        def worker():
            try:
                result = self.browser.send(room, message)
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

    def stop_listening(self, reason=""):
        was_listening = self.voice is not None
        self.stop_voice.set()
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
