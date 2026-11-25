"""Lightweight controls for the plain, light Windows control panel."""

from collections import OrderedDict
from functools import lru_cache
import math
from pathlib import Path
import tkinter as tk

from PIL import Image, ImageDraw, ImageFont, ImageTk


INK = "#263241"
MUTED = "#687586"
ACCENT = "#3B74CD"
SUCCESS = "#347A61"
SURFACE = "#FFFFFF"


@lru_cache(maxsize=32)
def _font(size, bold, dpi):
    pixels = max(10, round(size * dpi / 72))
    fonts = Path("C:/Windows/Fonts")
    for name in (("msyhbd.ttc", "msyh.ttc") if bold else ("msyh.ttc", "msyhbd.ttc")):
        try:
            return ImageFont.truetype(str(fonts / name), pixels)
        except OSError:
            pass
    return ImageFont.load_default(size=pixels)


def overlay(image, color, opacity, radius=0):
    layer = Image.new("RGBA", image.size)
    ImageDraw.Draw(layer).rounded_rectangle(
        (0, 0, image.width - 1, image.height - 1), radius=radius,
        fill=color + f"{round(opacity * 255):02x}")
    return Image.alpha_composite(image.convert("RGBA"), layer).convert("RGB")


def ellipsis(text, font, width):
    text = str(text)
    if width <= 0:
        return ""
    if font.getlength(text) <= width:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if font.getlength(text[:mid] + "…") <= width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + "…" if lo else ""


class PhotoCanvas(tk.Canvas):
    """Paint controls on their parent's solid background."""

    def __init__(self, master, **kwargs):
        self.rendered_image = None
        self._photo = None
        self._paint_job = None
        try:
            background = master.cget("background")
        except tk.TclError:
            background = SURFACE
        super().__init__(master, bd=0, highlightthickness=0, background=background, **kwargs)
        self.bind("<Configure>", lambda _: self.redraw(), add="+")
        self.bind("<Destroy>", self._destroyed, add="+")

    def _destroyed(self, event):
        if event.widget == self:
            if self._paint_job is not None:
                self.after_cancel(self._paint_job)
                self._paint_job = None
            self._photo = None

    def redraw(self):
        if self._paint_job is None:
            self._paint_job = self.after_idle(self._paint)

    def _paint(self):
        self._paint_job = None
        size = (max(1, self.winfo_width()), max(1, self.winfo_height()))
        if min(size) < 8:
            return
        background = tuple(value // 257 for value in self.winfo_rgb(tk.Canvas.cget(self, "background")))
        image = Image.new("RGB", size, background)
        self.draw_content(image)
        self.rendered_image = image
        self._photo = ImageTk.PhotoImage(image, master=self)
        self.delete("paint")
        self.create_image(0, 0, image=self._photo, anchor="nw", tags="paint")

    def draw_content(self, image):
        pass


class PhotoLabel(PhotoCanvas):
    def __init__(self, master, text="", fg=INK, bg=None, font=("Microsoft YaHei UI", 9),
                 padx=0, pady=0, anchor="center", **kwargs):
        self.options = dict(text=text, fg=fg, bg=bg, font=font, padx=padx, pady=pady, anchor=anchor)
        self.dpi = round(master.winfo_fpixels("1i"))
        super().__init__(master, **kwargs)
        self._measure()

    def _text_font(self):
        value = self.options["font"]
        return _font(int(value[1]), "bold" in value[2:], self.dpi)

    def _measure(self):
        font = self._text_font()
        width = min(600, math.ceil(font.getlength(self.options["text"]))) + self.options["padx"] * 2 + 2
        height = sum(font.getmetrics()) + self.options["pady"] * 2 + 2
        tk.Canvas.configure(self, width=width, height=height)
        self.redraw()

    def configure(self, cnf=None, **kwargs):
        if cnf:
            kwargs.update(cnf)
        for key in tuple(kwargs):
            if key in self.options:
                self.options[key] = kwargs.pop(key)
        if kwargs:
            tk.Canvas.configure(self, **kwargs)
        self._measure()

    config = configure

    def cget(self, key):
        return self.options[key] if key in self.options else super().cget(key)

    def draw_content(self, image):
        draw = ImageDraw.Draw(image)
        font = self._text_font()
        text = ellipsis(self.options["text"], font, image.width - self.options["padx"] * 2)
        if self.options["anchor"] == "w":
            x, anchor = self.options["padx"], "lm"
        else:
            x, anchor = image.width / 2, "mm"
        draw.text((x, image.height / 2), text, font=font, fill=self.options["fg"], anchor=anchor)


class PhotoButton(PhotoLabel):
    def __init__(self, master, command=None, state="normal", variant="quiet", **kwargs):
        self.command = command
        self.button_state = state
        self.variant = variant
        self.hovered = False
        self.pressed = False
        for key in ("activebackground", "activeforeground", "disabledforeground", "relief", "bd", "cursor"):
            kwargs.pop(key, None)
        kwargs.setdefault("padx", 16)
        kwargs.setdefault("pady", 8)
        super().__init__(master, takefocus=True, cursor="hand2", **kwargs)
        self.bind("<Enter>", lambda _: self._hover(True))
        self.bind("<Leave>", lambda _: self._hover(False))
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Key-space>", lambda _: self.invoke())
        self.bind("<Key-Return>", lambda _: self.invoke())
        self.bind("<FocusIn>", lambda _: self.redraw())
        self.bind("<FocusOut>", lambda _: self.redraw())

    def _destroyed(self, event):
        super()._destroyed(event)
        if event.widget == self:
            self.command = None

    def configure(self, cnf=None, **kwargs):
        if cnf:
            kwargs.update(cnf)
        self.button_state = kwargs.pop("state", self.button_state)
        for key in ("activebackground", "activeforeground", "disabledforeground"):
            kwargs.pop(key, None)
        super().configure(**kwargs)

    config = configure

    def cget(self, key):
        return self.button_state if key == "state" else super().cget(key)

    def _hover(self, value):
        self.hovered = value
        self.pressed = False
        self.redraw()

    def _press(self, _event):
        if self.button_state != "disabled":
            self.focus_set()
            self.pressed = True
            self.redraw()

    def _release(self, event):
        pressed = self.pressed
        self.pressed = False
        self.redraw()
        if pressed and 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height():
            self.invoke()

    def invoke(self):
        if self.button_state != "disabled" and self.command:
            return self.command()

    def draw_content(self, image):
        disabled = self.button_state == "disabled"
        primary = self.variant == "primary"
        color = (self.options["bg"] or ACCENT) if primary else ("#E6EDF7" if self.hovered else "#F0F3F7")
        if disabled:
            color = "#EDF0F4"
        image.paste(overlay(image, color, 1, 6))
        if self.focus_get() == self:
            ImageDraw.Draw(image).rounded_rectangle((1, 1, image.width - 2, image.height - 2),
                                                   radius=5, outline="#91B1E0", width=1)
        original = self.options["fg"]
        if disabled:
            self.options["fg"] = "#9AA3AF"
        super().draw_content(image)
        self.options["fg"] = original


class ModeButton(PhotoButton):
    def __init__(self, master, variable, value, command, **kwargs):
        self.variable, self.value, self.mode_command = variable, value, command
        super().__init__(master, command=self._choose, **kwargs)
        self._trace = variable.trace_add("write", lambda *_: self.redraw())
        self.bind("<Destroy>", self._remove_trace, add="+")

    def _remove_trace(self, event):
        if event.widget == self:
            self.variable.trace_remove("write", self._trace)
            self.variable = None
            self.mode_command = None

    def _choose(self):
        self.variable.set(self.value)
        self.mode_command()

    def draw_content(self, image):
        selected = self.variable.get() == self.value
        if selected:
            image.paste(overlay(image, "#E5EFFD", 1, 6))
            PhotoLabel.draw_content(self, image)
        else:
            super().draw_content(image)


class ScrollPhotoCanvas(PhotoCanvas):
    def __init__(self, master, **kwargs):
        self.offset = 0
        self.content_height = 0
        self._scroll_drag = False
        super().__init__(master, **kwargs)
        self.bind("<MouseWheel>", lambda e: self.yview("scroll", -int(e.delta / 120), "units"))
        self.bind("<Button-4>", lambda _: self.yview("scroll", -1, "units"))
        self.bind("<Button-5>", lambda _: self.yview("scroll", 1, "units"))
        self.bind("<ButtonPress-1>", self._scroll_press, add="+")
        self.bind("<B1-Motion>", self._scroll_motion, add="+")
        self.bind("<ButtonRelease-1>", lambda _: setattr(self, "_scroll_drag", False), add="+")

    def yview(self, *args):
        height = max(1, self.winfo_height())
        if args:
            if args[0] == "moveto":
                self.offset = float(args[1]) * self.content_height
            elif args[0] == "scroll":
                self.offset += int(args[1]) * (height if args[2] == "pages" else 32)
            self.offset = max(0, min(self.offset, max(0, self.content_height - height)))
            self.redraw()
        total = max(height, self.content_height)
        return self.offset / total, min(1, (self.offset + height) / total)

    def _scroll_press(self, event):
        if event.x >= self.winfo_width() - 12 and self.content_height > self.winfo_height():
            self._scroll_drag = True
            self._scroll_motion(event)

    def _scroll_motion(self, event):
        if self._scroll_drag:
            fraction = event.y / max(1, self.winfo_height())
            self.yview("moveto", fraction)

    def _scrollbar(self, image):
        height = image.height
        self.offset = max(0, min(self.offset, max(0, self.content_height - height)))
        if self.content_height > height and height >= 8 and image.width >= 12:
            track = height - 4
            size = min(track, max(24, height * height / self.content_height))
            fraction = self.offset / max(1, self.content_height - height)
            top = 2 + fraction * (track - size)
            ImageDraw.Draw(image).rounded_rectangle(
                (image.width - 4, top, image.width - 2, top + size),
                radius=1, fill="#AEB8C6")


class RoomTable(ScrollPhotoCanvas):
    """The small Treeview interface used by the control panel."""

    def __init__(self, master, columns, **kwargs):
        for name in ("show", "selectmode", "style"):
            kwargs.pop(name, None)
        kwargs["height"] = int(kwargs.get("height", 5)) * 37 + 34
        self.columns = columns
        self.headings = dict.fromkeys(columns, "")
        self.rows = OrderedDict()
        self.selected = None
        self.row_height, self.header_height = 38, 32
        self.dpi = round(master.winfo_fpixels("1i"))
        super().__init__(master, takefocus=True, **kwargs)
        self.bind("<ButtonPress-1>", self._click, add="+")
        for key in ("Up", "Down", "Home", "End", "Prior", "Next", "space"):
            self.bind(f"<KeyPress-{key}>", self._key)

    def heading(self, column, *, text):
        self.headings[column] = text

    def column(self, *_args, **_kwargs):
        pass

    def get_children(self):
        return tuple(self.rows)

    def insert(self, parent, index, iid, values):
        self.rows[str(iid)] = tuple(values)
        self.redraw()
        return str(iid)

    def delete(self, *items):
        # Canvas paint items use this method too.
        if items == ("paint",):
            return tk.Canvas.delete(self, *items)
        for item in items:
            self.rows.pop(str(item), None)
            if self.selected == str(item):
                self.selected = None
        self.redraw()

    def item(self, iid, option=None):
        values = self.rows[str(iid)]
        return values if option == "values" else {"values": values}

    def selection(self):
        return (self.selected,) if self.selected in self.rows else ()

    def selection_set(self, iid):
        if str(iid) in self.rows:
            changed = self.selected != str(iid)
            self.selected = str(iid)
            self.redraw()
            if changed:
                self.event_generate("<<TreeviewSelect>>", when="tail")

    def selection_remove(self, *items):
        if self.selected in items:
            self.selected = None
            self.redraw()

    def focus(self, iid=None):
        return self.selected or ""

    def see(self, iid):
        if str(iid) not in self.rows:
            return
        top = list(self.rows).index(str(iid)) * self.row_height
        available = max(self.row_height, self.winfo_height() - self.header_height)
        self.offset = max(0, min(self.offset, top)) if top < self.offset else max(self.offset, top + self.row_height - available)
        self.redraw()

    def _click(self, event):
        self.focus_set()
        if event.y < self.header_height or event.x >= self.winfo_width() - 12:
            return
        index = int((event.y - self.header_height + self.offset) // self.row_height)
        keys = list(self.rows)
        if 0 <= index < len(keys):
            self.selection_set(keys[index])

    def _key(self, event):
        keys = list(self.rows)
        if not keys:
            return
        index = keys.index(self.selected) if self.selected in keys else -1
        jump = max(1, (self.winfo_height() - self.header_height) // self.row_height)
        if event.keysym in ("Up", "Prior"):
            index -= jump if event.keysym == "Prior" else 1
        elif event.keysym in ("Down", "Next"):
            index += jump if event.keysym == "Next" else 1
        elif event.keysym == "Home":
            index = 0
        elif event.keysym == "End":
            index = len(keys) - 1
        self.selection_set(keys[max(0, min(len(keys) - 1, index))])
        self.see(self.selected)
        return "break"

    def draw_content(self, image):
        draw = ImageDraw.Draw(image)
        font = _font(9, False, self.dpi)
        heading_font = _font(8, False, self.dpi)
        self.content_height = self.header_height + len(self.rows) * self.row_height
        self.offset = min(self.offset, max(0, self.content_height - image.height))
        available = max(1, image.width - 28)
        widths = [available * share for share in (0.08, 0.13, 0.32, 0.15, 0.32)]
        starts = [12]
        for width in widths[:-1]:
            starts.append(starts[-1] + width)
        for index, (iid, values) in enumerate(self.rows.items()):
            y = self.header_height + index * self.row_height - self.offset
            if y < self.header_height or y + self.row_height > image.height + self.row_height:
                continue
            if iid == self.selected:
                layer = Image.new("RGBA", image.size)
                shade = ImageDraw.Draw(layer)
                shade.rounded_rectangle((3, y + 1, image.width - 12, y + self.row_height - 3),
                                        radius=5, fill="#E9F1FE")
                image.paste(Image.alpha_composite(image.convert("RGBA"), layer).convert("RGB"))
                draw = ImageDraw.Draw(image)
                draw.rounded_rectangle((3, y + 9, 4, y + self.row_height - 11), radius=1, fill=ACCENT)
            for col, value in enumerate(values):
                color = (SUCCESS if str(value) == "可发送" else "#9A7336") if col == 3 else (MUTED if col == 4 else INK)
                if col == 0:
                    value = {"bilibili": "B站", "douyu": "斗鱼", "douyin": "抖音"}.get(value, value)
                draw.text((starts[col], y + self.row_height / 2),
                          ellipsis(value, font, widths[col] - 12), font=font, fill=color, anchor="lm")
        # Header is fixed while the data scrolls.
        header = Image.new("RGB", (image.width, self.header_height), "#F5F7FA")
        image.paste(header, (0, 0))
        draw = ImageDraw.Draw(image)
        for index, column in enumerate(self.columns):
            draw.text((starts[index], self.header_height / 2), self.headings[column],
                      font=heading_font, fill=MUTED, anchor="lm")
        if not self.rows:
            draw.text((image.width / 2, max(60, image.height / 2)), "打开直播网页后，房间会显示在这里",
                      font=font, fill=MUTED, anchor="mm")
        self._scrollbar(image)


class ActivityLog(ScrollPhotoCanvas):
    def __init__(self, master, **kwargs):
        self.entries = []
        self.colors = {"success": SUCCESS, "error": "#B24C5D", "recognized": ACCENT}
        self._wrapped = []
        self._wrap_key = None
        self._line_cache = OrderedDict()
        self._wrap_width = None
        self._glyph_widths = {}
        self._follow_end = True
        self._selection_start = None
        self._selection_end = None
        self.dpi = round(master.winfo_fpixels("1i"))
        super().__init__(master, height=130, takefocus=True, **kwargs)
        self.bind("<Control-c>", lambda _: self.copy_selection())
        self.bind("<Control-a>", self._select_all)
        self.bind("<ButtonPress-1>", self._select_start, add="+")
        self.bind("<B1-Motion>", self._select_drag, add="+")

    def append(self, text, tag=""):
        self.entries.append((text.rstrip("\n"), tag))
        self.entries = self.entries[-1000:]
        self._follow_end = True
        self._selection_start = self._selection_end = None
        self.redraw()

    def copy_all(self):
        text = "\n".join(text for text, _ in self.entries)
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)
        return "break"

    def _point(self, event):
        font = _font(9, False, self.dpi)
        line_height = sum(font.getmetrics()) + 8
        index = max(0, min(len(self._wrapped) - 1, int((event.y - 8 + self.offset) // line_height)))
        if not self._wrapped:
            return 0, 0
        text = self._wrapped[index][0]
        x = max(0, event.x - 10)
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if font.getlength(text[:mid]) <= x:
                lo = mid
            else:
                hi = mid - 1
        return index, lo

    def _select_start(self, event):
        self.focus_set()
        if self._scroll_drag:
            return
        self._selection_start = self._selection_end = self._point(event)
        self.redraw()

    def _select_drag(self, event):
        if not self._scroll_drag and self._selection_start is not None:
            self._selection_end = self._point(event)
            self.redraw()

    def _select_all(self, _event=None):
        if self._wrapped:
            self._selection_start = (0, 0)
            self._selection_end = (len(self._wrapped) - 1, len(self._wrapped[-1][0]))
            self.redraw()
        return "break"

    def copy_selection(self):
        if self._selection_start is None or self._selection_end == self._selection_start:
            return "break"
        start, end = sorted((self._selection_start, self._selection_end))
        lines = [text for text, _ in self._wrapped[start[0]:end[0] + 1]]
        if lines:
            lines[-1] = lines[-1][:end[1]]
            lines[0] = lines[0][start[1]:]
            self.clipboard_clear()
            self.clipboard_append("\n".join(lines))
        return "break"

    def yview(self, *args):
        if args:
            self._follow_end = False
        return super().yview(*args)

    def draw_content(self, image):
        font = _font(9, False, self.dpi)
        width = max(40, image.width - 32)
        key = (width, len(self.entries), self.entries[-1] if self.entries else None)
        if key != self._wrap_key:
            self._wrapped = []
            if width != self._wrap_width:
                self._line_cache.clear()
                self._wrap_width = width
            for text, tag in self.entries:
                lines = self._line_cache.get(text)
                if lines is None:
                    lines = []
                    line, used = "", 0
                    for char in text:
                        if char not in self._glyph_widths:
                            self._glyph_widths[char] = font.getlength(char)
                        pixels = self._glyph_widths[char]
                        if used + pixels > width and line:
                            lines.append(line)
                            line, used = "", 0
                        line += char
                        used += pixels
                    lines.append(line)
                    self._line_cache[text] = lines
                self._line_cache.move_to_end(text)
                self._wrapped.extend((line, tag) for line in lines)
            while len(self._line_cache) > 1000:
                self._line_cache.popitem(last=False)
            self._wrap_key = key
        line_height = sum(font.getmetrics()) + 8
        self.content_height = len(self._wrapped) * line_height + 16
        if self._follow_end:
            self.offset = max(0, self.content_height - image.height)
        self.offset = max(0, min(self.offset, max(0, self.content_height - image.height)))
        draw = ImageDraw.Draw(image)
        for index, (text, tag) in enumerate(self._wrapped):
            y = 8 + index * line_height - self.offset
            if -line_height < y < image.height:
                if self._selection_start is not None and self._selection_end is not None:
                    start, end = sorted((self._selection_start, self._selection_end))
                    if start[0] <= index <= end[0]:
                        left = start[1] if index == start[0] else 0
                        right = end[1] if index == end[0] else len(text)
                        x1, x2 = 10 + font.getlength(text[:left]), 10 + font.getlength(text[:right])
                        draw.rectangle((x1, y - 1, x2, y + line_height - 4), fill="#DCE8FA")
                draw.text((10, y), text, font=font, fill=self.colors.get(tag, MUTED), anchor="lt")
        if not self.entries:
            draw.text((12, 18), "识别文本、排队和发送结果将在这里显示。", font=font, fill=MUTED, anchor="lt")
        self._scrollbar(image)
