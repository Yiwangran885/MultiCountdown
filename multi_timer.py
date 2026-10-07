# -*- coding: utf-8 -*-
"""多任务倒计时器

功能：
- 计时倒计时：可随时新建/编辑（双击卡片），独立命名；同一时刻最多只有一个在倒计时，
  启动新的会自动暂停正在计时的那个；结束有提示音、置顶提醒和界面高亮；每日自动重置；
- 日期倒计时：指定目标日期（生日、考研日期等），按天显示剩余，可每年重复；
  置顶的固定显示在窗口顶部，滚动列表时不动；
- 卡片外观：每张卡片可自定义背景颜色或图片（图片自动暗化保证文字可读）；
- 窗口效果：毛玻璃透明（Win11）/ 半透明 / 不透明，可设置窗口置顶和开机自启动；
- 数据保存在同目录 timers.json / settings.json，下次打开自动恢复（跨天计时自动重置）。

用法：
    python multi_timer.py            # 正常启动
    python multi_timer.py --selftest # 运行内置自检（不显示窗口）
"""

import datetime
import json
import math
import os
import re
import subprocess
import sys
import threading
import time as time_mod
import tkinter as tk
from ctypes import byref, c_int, Structure, windll
from tkinter import colorchooser, filedialog, messagebox

if getattr(sys, "frozen", False):
    # PyInstaller 打包后 __file__ 指向临时解压目录，数据必须跟着 exe 走
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(APP_DIR, "timers.json")
SETTINGS_FILE = os.path.join(APP_DIR, "settings.json")
ICON_FILE = os.path.join(APP_DIR, "timer_icon.ico")

IDLE, RUNNING, PAUSED, DONE = "未开始", "运行中", "已暂停", "已完成"

FONT = "Microsoft YaHei UI"
MAGIC = "#010101"          # 毛玻璃模式的透明键色（窗口上此颜色处透出亚克力模糊）

ACCENT = {IDLE: "#8b949e", RUNNING: "#1a7f37", PAUSED: "#d4a72c", DONE: "#8250df"}
PIN_BLUE, DATE_BLUE = "#0969da", "#2f81f7"
GREEN, BLUE = "#1a7f37", "#2563eb"

SWATCHES = ["#ffffff", "#ffe3e3", "#fff3bf", "#d3f9d8", "#d0ebff", "#e5dbff",
            "#ffd8a8", "#c3fae8", "#f1f3f5", "#343a40", "#212f3d", "#5f3dc4"]

THEMES = {
    "glass": {"bg": MAGIC, "text": "#f3f6fc", "muted": "#98a2b3", "card": "#272d38",
              "border": "#3a4150", "track": "#39414f",
              "chip": {IDLE: "#333b49", RUNNING: "#1d3b2b", PAUSED: "#3d3420", DONE: "#322a4e"},
              "chip_fg": {IDLE: "#aeb9c9", RUNNING: "#7ee2a8", PAUSED: "#ffd666", DONE: "#c9a7ff"},
              "time": {IDLE: "#aeb9c9", RUNNING: "#7ee2a8", PAUSED: "#ffd666", DONE: "#c9a7ff"},
              "sec_btn": "#3a4150", "sec_btn_fg": "#e6ebf3", "sec_btn_border": "#454e5e",
              "panel": "#1b2432", "panel_border": "#33415a", "panel_title": "#7ab3ff",
              "date_big": "#7ab3ff", "empty": "#8fa0b5"},
    "light": {"bg": "#f2f4f7", "text": "#1f2328", "muted": "#6e7781", "card": "#ffffff",
              "border": "#d8dee4", "track": "#eaeef2",
              "chip": {IDLE: "#eef1f4", RUNNING: "#ddf2e5", PAUSED: "#fdf3cd", DONE: "#f1e6fd"},
              "chip_fg": {IDLE: "#57606a", RUNNING: "#1a7f37", PAUSED: "#9a6700", DONE: "#8250df"},
              "time": {IDLE: "#57606a", RUNNING: "#1a7f37", PAUSED: "#9a6700", DONE: "#8250df"},
              "sec_btn": "#ffffff", "sec_btn_fg": "#1f2328", "sec_btn_border": "#d8dee4",
              "panel": "#e9f0fb", "panel_border": "#c6d8f5", "panel_title": "#1d4ed8",
              "date_big": "#1d4ed8", "empty": "#8b949e"},
}

DEFAULT_SETTINGS = {"theme": "glass", "opacity": 0.9, "topmost": False, "autostart": False}

RUN_KEY = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VAL = "MultiCountdownTimer"


class MARGINS(Structure):
    _fields_ = [("cxLeftWidth", c_int), ("cxRightWidth", c_int),
                ("cyTopHeight", c_int), ("cyBottomHeight", c_int)]


def _mix(hex1, hex2, f):
    """hex1 向 hex2 混合 f（0-1）。"""
    a = (int(hex1[1:3], 16), int(hex1[3:5], 16), int(hex1[5:7], 16))
    b = (int(hex2[1:3], 16), int(hex2[3:5], 16), int(hex2[5:7], 16))
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * f) for x, y in zip(a, b))


def _lum(hexs):
    return 0.299 * int(hexs[1:3], 16) + 0.587 * int(hexs[3:5], 16) + 0.114 * int(hexs[5:7], 16)


def _rrect_pts(x1, y1, x2, y2, r):
    return [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
            x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]


def _norm_color(hexs):
    if not isinstance(hexs, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", hexs):
        return None
    hexs = hexs.lower()
    return "#020202" if hexs == MAGIC else hexs   # 避免用户选纯黑击穿透明键色


def load_settings():
    s = dict(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            for k in DEFAULT_SETTINGS:
                if k in d:
                    s[k] = d[k]
    except (OSError, ValueError):
        pass
    return s


def save_settings(s):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def _autostart_cmd():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'          # 打包版：自启动指向 exe 本身
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if not os.path.exists(pyw):
        pyw = exe
    return f'"{pyw}" "{os.path.abspath(__file__)}"'


def autostart_enabled():
    try:
        r = subprocess.run(["reg", "query", RUN_KEY, "/v", RUN_VAL],
                           capture_output=True, text=True, encoding="gbk", errors="replace",
                           creationflags=0x08000000)
        return r.returncode == 0 and RUN_VAL.lower() in (r.stdout or "").lower()
    except Exception:
        return False


def set_autostart(on):
    try:
        if on:
            subprocess.run(["reg", "add", RUN_KEY, "/v", RUN_VAL, "/t", "REG_SZ",
                            "/d", _autostart_cmd(), "/f"],
                           capture_output=True, creationflags=0x08000000, check=True)
        else:
            subprocess.run(["reg", "delete", RUN_KEY, "/v", RUN_VAL, "/f"],
                           capture_output=True, creationflags=0x08000000, check=True)
        return True
    except Exception:
        return False


def fmt(sec: float) -> str:
    s = max(0, int(math.ceil(sec - 1e-6)))
    h, rem = divmod(s, 3600)
    m, ss = divmod(rem, 60)
    return f"{h}:{m:02d}:{ss:02d}" if h else f"{m:02d}:{ss:02d}"


class TimerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.timers = []   # timer: {type,id,name,duration,remaining,base,since,state,color,image}
                           # date:  {type,id,name,target,recurring,pinned,color,image}
        self.rows = {}     # id -> 卡片信息（canvas + 各元素 id）
        self.next_id = 1
        self.silent = False
        self._status_hold = 0.0
        self._date_refresh = 0.0
        self._today = datetime.date.today()
        self._img_cache = {}
        self.settings = load_settings()

        root.title("多倒计时器")
        root.geometry("480x640")
        root.minsize(420, 440)
        try:
            root.iconbitmap(ICON_FILE)     # 标题栏与任务栏图标
        except tk.TclError:
            pass
        self._rebuild_ui()
        self._load()
        self._rebuild_list()
        self._tick()
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------- 窗口效果与主题 ----------------

    def _resolve_theme(self):
        mode = self.settings.get("theme", "glass")
        if mode == "glass":
            if getattr(self, "_glass_failed", False):
                return "alpha", "light"
            try:
                if sys.getwindowsversion().build >= 22621:
                    return "glass", "glass"
            except Exception:
                pass
            return "alpha", "light"
        return mode, "light"

    def _apply_window_effect(self):
        root = self.root
        mode = self._mode
        for att, val in (("-alpha", 1.0), ("-transparentcolor", "#00fffe")):
            try:
                root.attributes(att, val)
            except tk.TclError:
                pass
        if mode == "glass":
            try:
                root.update_idletasks()
                root.update()          # 先让窗口完成映射，否则拿到的 HWND 无效
                hwnd = windll.user32.GetAncestor(root.winfo_id(), 2)   # GA_ROOT
                if not hwnd:
                    hwnd = windll.user32.GetParent(root.winfo_id())
                if not hwnd:
                    raise OSError("窗口句柄未就绪")
                rc = windll.dwmapi.DwmSetWindowAttribute(hwnd, 38, byref(c_int(3)), 4)  # 亚克力
                windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, byref(c_int(1)), 4)       # 深色标题栏
                windll.dwmapi.DwmExtendFrameIntoClientArea(hwnd, byref(MARGINS(-1, -1, -1, -1)))
                if rc != 0:
                    raise OSError("DWM backdrop 不可用")
                root.configure(bg=MAGIC)
                root.attributes("-transparentcolor", MAGIC)   # 键色处透出毛玻璃
            except Exception:
                self._glass_failed = True
                self._mode = "alpha"
                self.T = THEMES["light"]
                root.configure(bg=self.T["bg"])
                root.after(0, self._rebuild_ui)               # 以浅色主题重建一次
                mode = "alpha"
        elif mode == "alpha":
            try:
                root.attributes("-alpha", float(self.settings.get("opacity", 0.9)))
            except tk.TclError:
                pass
            root.configure(bg=self.T["bg"])
        else:
            root.configure(bg=self.T["bg"])
        self._topmost = bool(self.settings.get("topmost"))
        try:
            root.attributes("-topmost", self._topmost)
        except tk.TclError:
            pass

    def _rebuild_ui(self):
        for w in self.root.winfo_children():
            w.destroy()
        self._mode, key = self._resolve_theme()
        self.T = THEMES[key]
        self._build_ui()
        self._apply_window_effect()
        self._rebuild_list()

    # ---------------- UI ----------------

    def _build_ui(self):
        T = self.T
        header = tk.Frame(self.root, bg=T["bg"])
        header.pack(fill="x")
        tk.Label(header, text="多倒计时器", bg=T["bg"], fg=T["text"],
                 font=(FONT, 13, "bold")).pack(side="left", padx=14, pady=10)
        hb = tk.Frame(header, bg=T["bg"])
        hb.pack(side="right", padx=12)
        self._btn(hb, "＋ 计时", self._timer_dialog, bg=BLUE, fg="white", bold=True
                  ).pack(side="left", padx=3, pady=8)
        self._btn(hb, "＋ 日期", lambda: self._date_dialog(), bg=GREEN, fg="white", bold=True
                  ).pack(side="left", padx=3, pady=8)
        self._btn(hb, "⚙ 设置", self._settings_dialog
                  ).pack(side="left", padx=3, pady=8)
        tk.Frame(self.root, bg=T["border"], height=1).pack(fill="x")

        # 置顶区固定在滚动列表之外：无论怎么滚动，置顶日期都保持在窗口顶部
        self.pinned_frame = tk.Frame(self.root, bg=T["bg"])
        self.pinned_frame.pack(fill="x", padx=12, pady=(8, 0))

        holder = tk.Frame(self.root, bg=T["bg"])
        holder.pack(fill="both", expand=True, padx=12, pady=6)
        self.canvas = tk.Canvas(holder, bg=T["bg"], highlightthickness=0)
        vsb = ttk_scrollbar(holder, self.canvas)
        vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=T["bg"])
        self.inner_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>",
                        lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfigure(self.inner_id, width=e.width))
        self.canvas.bind_all("<MouseWheel>",
                             lambda e: self.canvas.yview_scroll(-int(e.delta / 120), "units"))

        tk.Frame(self.root, bg=T["border"], height=1).pack(fill="x", side="bottom")
        self.status = tk.Label(self.root, text="", bg=T["bg"], fg=T["muted"],
                               font=(FONT, 9), anchor="w", pady=6)
        self.status.pack(fill="x", side="bottom", padx=12)

    def _btn(self, parent, text, cmd, bg="#ffffff", fg="#1f2328", bold=False, padx=10, border=None):
        solid = border is None
        hov = _mix(bg, "#000000" if _lum(bg) > 60 else "#ffffff", 0.08)
        b = tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg,
                      activebackground=hov, activeforeground=fg,
                      relief="flat", bd=0, padx=padx, pady=3, cursor="hand2",
                      highlightthickness=0 if solid else 1,
                      highlightbackground=border or bg,
                      font=(FONT, 10, "bold" if bold else "normal"))
        b.bind("<Enter>", lambda e: b.config(bg=hov))
        b.bind("<Leave>", lambda e: b.config(bg=bg))
        return b

    def _entry(self, parent, **kw):
        return tk.Entry(parent, relief="flat", highlightthickness=1,
                        highlightbackground="#d0d7de", highlightcolor=BLUE, **kw)

    def _spinbox(self, parent, **kw):
        # Spinbox 与 Entry 是不同控件：from_/to 只有 Spinbox 支持，
        # 误用 Entry 会在创建时抛 TclError，导致编辑弹窗只画出一半
        return tk.Spinbox(parent, relief="flat", highlightthickness=1,
                          highlightbackground="#d0d7de", highlightcolor=BLUE,
                          buttonbackground="#f6f8fa", **kw)

    def _section_head(self, parent, text, dot):
        bar = tk.Frame(parent, bg=self.T["bg"])
        bar.pack(fill="x", pady=(12, 4))
        tk.Label(bar, text="●", fg=dot, bg=self.T["bg"], font=(FONT, 8)).pack(side="left")
        tk.Label(bar, text="  " + text, fg=self.T["muted"], bg=self.T["bg"],
                 font=(FONT, 10, "bold"), anchor="w").pack(side="left")

    def _sections(self):
        """返回 (置顶日期, 计时, 普通日期) 三个有序列表；置顶日期固定在滚动区外。"""
        timers = [t for t in self.timers if t.get("type") != "date"]
        all_dates = [t for t in self.timers if t.get("type") == "date"]
        pinned = sorted((d for d in all_dates if d.get("pinned")),
                        key=lambda d: self._next_target(d))
        rest = sorted((d for d in all_dates if not d.get("pinned")),
                      key=lambda d: self._next_target(d))
        return pinned, timers, rest

    def _rebuild_list(self):
        for w in self.inner.winfo_children():
            w.destroy()
        for w in self.pinned_frame.winfo_children():
            w.destroy()
        self.rows.clear()
        pinned, timers, dates = self._sections()

        # 置顶区固定在滚动区外：怎么滚动列表都不动
        if pinned:
            panel = tk.Frame(self.pinned_frame, bg=self.T["panel"], highlightthickness=1,
                             highlightbackground=self.T["panel_border"])
            panel.pack(fill="x")
            innerp = tk.Frame(panel, bg=self.T["panel"])
            innerp.pack(fill="x", padx=10, pady=(6, 8))
            tk.Label(innerp, text="📌 置顶", bg=self.T["panel"], fg=self.T["panel_title"],
                     font=(FONT, 10, "bold"), anchor="w").pack(fill="x", pady=(0, 4))
            for d in pinned:
                self._make_date_row(d, innerp)

        if not timers and not dates:
            if pinned:
                tk.Label(self.inner, text="计时和其他日期倒计时会显示在这里",
                         bg=self.T["bg"], fg=self.T["empty"], font=(FONT, 10), justify="center"
                         ).pack(fill="x", expand=True, pady=40)
            else:
                tk.Label(self.inner, text="⏳  还没有倒计时\n\n点击右上角「＋ 计时」或「＋ 日期」添加",
                         bg=self.T["bg"], fg=self.T["empty"], font=(FONT, 11), justify="center"
                         ).pack(fill="x", expand=True, pady=60)
            self._tick_once()
            return

        if timers:
            self._section_head(self.inner, "计时倒计时 · 同一时刻只计时一个", GREEN)
            for t in timers:
                self._make_row(t)
        if dates:
            self._section_head(self.inner, "日期倒计时 · 按天倒数", DATE_BLUE)
            for d in dates:
                self._make_date_row(d, self.inner)
        self._tick_once()

    # ---------------- 卡片绘制（Canvas 圆角卡） ----------------

    def _card_canvas(self, parent, h):
        cv = tk.Canvas(parent, height=h, bg=parent["bg"], highlightthickness=0, bd=0)
        cv.pack(fill="x", pady=4)
        return cv

    def _card_pal(self, t):
        """卡片配色：图片 > 自定义颜色 > 主题默认。"""
        theme = self.T
        st = t.get("state") if t.get("type") != "date" else None
        accent = ACCENT[st] if st else (PIN_BLUE if t.get("pinned") else DATE_BLUE)
        if t.get("image") and os.path.exists(t["image"]):
            return {"img": True, "card": None, "border": None, "frame": "#1a2029",
                    "text": "#f3f6fc", "muted": "#c3cad6",
                    "chip_bg": "#1a2029", "chip_fg": "#dfe6f2", "time": "#ffffff",
                    "btn": "#2a3140", "btn_fg": "#e6ebf3", "btn_border": "#3a4150",
                    "track": "#39414f", "accent": accent, "custom": False}
        custom = _norm_color(t.get("color"))
        if custom:
            dark = _lum(custom) < 140
            toward = "#ffffff" if dark else "#000000"
            text = "#f3f6fc" if dark else "#1f2328"
            return {"img": False, "card": custom, "border": _mix(custom, toward, 0.18),
                    "frame": custom, "text": text, "muted": _mix(text, custom, 0.35),
                    "chip_bg": _mix(custom, toward, 0.09), "chip_fg": text,
                    "time": text, "btn": _mix(custom, toward, 0.06), "btn_fg": text,
                    "btn_border": _mix(custom, toward, 0.16),
                    "track": _mix(custom, toward, 0.12), "accent": accent, "custom": True}
        return {"img": False, "card": theme["card"], "border": theme["border"],
                "frame": theme["card"], "text": theme["text"], "muted": theme["muted"],
                "chip_bg": theme["chip"][st] if st else theme["panel"],
                "chip_fg": theme["chip_fg"][st] if st else theme["muted"],
                "time": theme["time"][st] if st else theme["date_big"],
                "btn": theme["sec_btn"], "btn_fg": theme["sec_btn_fg"],
                "btn_border": theme["sec_btn_border"], "track": theme["track"],
                "accent": accent, "custom": False}

    def _card_image(self, path):
        """读取图片并加工成卡片背景（居中裁剪 + 暗化蒙版 + 圆角）。"""
        if path in self._img_cache:
            return self._img_cache[path]
        try:
            from PIL import Image, ImageDraw, ImageOps, ImageTk
            W, H = 1100, 104
            im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
            scale = max(W / im.width, H / im.height)
            im = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))))
            left = (im.width - W) // 2
            top = (im.height - H) // 2
            im = im.crop((left, top, left + W, top + H))
            im = Image.blend(im, Image.new("RGB", im.size, (18, 22, 30)), 0.52)
            mask = Image.new("L", (W * 2, H * 2), 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, W * 2 - 1, H * 2 - 1), radius=24, fill=255)
            mask = mask.resize((W, H))
            im = im.convert("RGBA")
            im.putalpha(mask)
            photo = ImageTk.PhotoImage(im)
            self._img_cache[path] = photo
            return photo
        except Exception:
            return None

    def _make_row(self, t):
        H = 104
        pal = self._card_pal(t)
        photo = self._card_image(t["image"]) if pal["img"] else None
        if pal["img"] and photo is None:      # 图片加载失败 → 回退颜色卡
            t["image"] = None
            pal = self._card_pal(t)
        cv = self._card_canvas(self.inner, H)
        row = {"cv": cv, "timer": t, "H": H, "ptrack": None}
        self.rows[t["id"]] = row

        if photo is not None:
            cv.create_image(0, 0, anchor="nw", image=photo)
        else:
            row["bg_item"] = cv.create_polygon(*_rrect_pts(1, 1, 60, H - 1, 12), smooth=True,
                                               fill=pal["card"], outline=pal["border"], width=1)
        cv.create_rectangle(12, 18, 16, H - 18, fill=pal["accent"], width=0)
        cv.create_text(26, 18, anchor="w", text=t["name"], fill=pal["text"],
                       font=(FONT, 11, "bold"))
        chip_lbl = tk.Label(cv, text=t["state"], bg=pal["chip_bg"], fg=pal["chip_fg"],
                            font=(FONT, 9, "bold"), padx=8, pady=1)
        row["chip_win"] = cv.create_window(0, 20, anchor="ne", window=chip_lbl)
        row["time"] = cv.create_text(26, 56, anchor="w", text=fmt(self.cur_remaining(t)),
                                     fill=pal["time"], font=("Consolas", 24, "bold"))

        btns = tk.Frame(cv, bg=pal["frame"])
        if t["state"] == RUNNING:
            self._btn(btns, "⏸ 暂停", lambda tt=t: self.pause(tt),
                      bg="#9a6700", fg="white").pack(side="left", padx=3)
        elif t["state"] == DONE:
            self._btn(btns, "↻ 重新开始", lambda tt=t: self.start(tt),
                      bg="#8250df", fg="white").pack(side="left", padx=3)
        else:
            self._btn(btns, "▶ 开始", lambda tt=t: self.start(tt),
                      bg=GREEN, fg="white").pack(side="left", padx=3)
        self._btn(btns, "重置", lambda tt=t: self.reset(tt),
                  bg=pal["btn"], fg=pal["btn_fg"], border=pal["btn_border"]).pack(side="left", padx=3)
        self._btn(btns, "编辑", lambda tt=t: self._timer_dialog(tt),
                  bg=pal["btn"], fg=pal["btn_fg"], border=pal["btn_border"]).pack(side="left", padx=3)
        self._btn(btns, "删除", lambda tt=t: self.delete(tt),
                  bg=pal["btn"], fg="#ff7b72", border=pal["btn_border"]).pack(side="left", padx=3)
        row["btns_win"] = cv.create_window(0, 62, anchor="e", window=btns)

        row["ptrack"] = cv.create_rectangle(26, H - 16, 40, H - 11, fill=pal["track"], width=0)
        row["pfill"] = cv.create_rectangle(26, H - 16, 26, H - 11,
                                           fill=ACCENT[t["state"]], width=0)

        cv.bind("<Configure>", lambda e: self._layout_card(t))
        self._layout_card(t)

        for w in (cv,):
            w.bind("<Double-Button-1>", lambda e, tt=t: self._timer_dialog(tt))

    def _layout_card(self, t):
        row = self.rows.get(t["id"])
        if not row:
            return
        cv = row["cv"]
        W = cv.winfo_width()
        H = row["H"]
        if W < 40:
            return
        row["W"] = W
        if row.get("bg_item"):
            cv.coords(row["bg_item"], *_rrect_pts(1, 1, W - 1, H - 1, 12))
        cv.coords(row["chip_win"], W - 14, 20)
        cv.coords(row["btns_win"], W - 14, 62)
        if row.get("ptrack"):
            cv.coords(row["ptrack"], 26, H - 16, W - 14, H - 11)
            self._draw_prog(t)

    def _draw_prog(self, t):
        row = self.rows.get(t["id"])
        if not row or not row.get("pfill"):
            return
        cv = row["cv"]
        W = row.get("W") or cv.winfo_width()
        H = row["H"]
        if W < 40:
            return
        dur = t["duration"] or 1
        frac = 0.0 if t["state"] == DONE else max(0.0, min(1.0, self.cur_remaining(t) / dur))
        cv.coords(row["pfill"], 26, H - 16, 26 + (W - 40) * frac, H - 11)
        cv.itemconfig(row["pfill"], fill=ACCENT[t["state"]])

    # ---------------- 日期倒计时 ----------------

    def _next_target(self, d):
        try:
            y, m, dd = (int(x) for x in d["target"].split("-"))
            date = datetime.date(y, m, dd)
        except (ValueError, KeyError):
            return datetime.date.today()
        today = datetime.date.today()
        if d.get("recurring"):
            while date < today:
                try:
                    date = date.replace(year=date.year + 1)
                except ValueError:          # 2月29日
                    date = date.replace(year=date.year + 1, day=28)
        return date

    def _days_left(self, d):
        return (self._next_target(d) - datetime.date.today()).days

    def _date_texts(self, d):
        tgt = self._next_target(d)
        days = (tgt - datetime.date.today()).days
        if days == 0:
            big = "🎉 就是今天！"
        elif days > 0:
            big = f"还有 {days} 天"
        else:
            big = f"已过 {-days} 天"
        wd = "周" + "一二三四五六日"[tgt.weekday()]
        small = f"目标：{tgt.isoformat()}（{wd}）"
        if d.get("recurring"):
            badge = "每年重复"
        elif days < 0:
            badge = "已过期"
        else:
            badge = "单次"
        if d.get("pinned"):
            badge = "📌 " + badge
        return big, small, badge, days

    def _make_date_row(self, d, parent=None):
        H = 104
        big, small, badge, days = self._date_texts(d)
        pal = self._card_pal(d)
        photo = self._card_image(d["image"]) if pal["img"] else None
        if pal["img"] and photo is None:
            d["image"] = None
            pal = self._card_pal(d)
        theme = self.T
        if pal["img"]:
            bigfg = "#98a2b3" if days < 0 else "#ffffff"
        elif pal["custom"]:
            bigfg = pal["muted"] if days < 0 else pal["text"]
        else:
            bigfg = theme["muted"] if days < 0 else theme["date_big"]

        cv = self._card_canvas(parent or self.inner, H)
        row = {"cv": cv, "timer": d, "H": H}
        self.rows[d["id"]] = row

        if photo is not None:
            cv.create_image(0, 0, anchor="nw", image=photo)
        else:
            row["bg_item"] = cv.create_polygon(*_rrect_pts(1, 1, 60, H - 1, 12), smooth=True,
                                               fill=pal["card"], outline=pal["border"], width=1)
        cv.create_rectangle(12, 18, 16, H - 18, fill=pal["accent"], width=0)
        cv.create_text(26, 18, anchor="w", text=d["name"], fill=pal["text"],
                       font=(FONT, 11, "bold"))
        badge_lbl = tk.Label(cv, text=badge, bg=pal["chip_bg"], fg=pal["chip_fg"],
                             font=(FONT, 9, "bold"), padx=8, pady=1)
        row["chip_win"] = cv.create_window(0, 20, anchor="ne", window=badge_lbl)
        row["badge"] = badge_lbl
        row["big"] = cv.create_text(26, 54, anchor="w", text=big, fill=bigfg,
                                    font=(FONT, 20, "bold"))
        row["small"] = cv.create_text(26, 82, anchor="w", text=small, fill=pal["muted"],
                                      font=(FONT, 9))

        btns = tk.Frame(cv, bg=pal["frame"])
        self._btn(btns, "取消置顶" if d.get("pinned") else "📌 置顶",
                  lambda dd=d: self.toggle_pin(dd),
                  bg=pal["btn"], fg=pal["btn_fg"], border=pal["btn_border"]).pack(side="left", padx=3)
        self._btn(btns, "编辑", lambda dd=d: self._date_dialog(dd),
                  bg=pal["btn"], fg=pal["btn_fg"], border=pal["btn_border"]).pack(side="left", padx=3)
        self._btn(btns, "删除", lambda dd=d: self.delete(dd),
                  bg=pal["btn"], fg="#ff7b72", border=pal["btn_border"]).pack(side="left", padx=3)
        row["btns_win"] = cv.create_window(0, 62, anchor="e", window=btns)

        cv.bind("<Configure>", lambda e: self._layout_card(d))
        self._layout_card(d)

    def _refresh_date_rows(self):
        for t in self.timers:
            if t.get("type") != "date":
                continue
            row = self.rows.get(t["id"])
            if not row or "big" not in row:
                continue
            big, small, badge, days = self._date_texts(t)
            pal = self._card_pal(t)
            theme = self.T
            if pal["img"]:
                bigfg = "#98a2b3" if days < 0 else "#ffffff"
            elif pal["custom"]:
                bigfg = pal["muted"] if days < 0 else pal["text"]
            else:
                bigfg = theme["muted"] if days < 0 else theme["date_big"]
            row["cv"].itemconfig(row["big"], text=big, fill=bigfg)
            row["cv"].itemconfig(row["small"], text=small)
            row["badge"].config(text=badge)

    def _date_dialog(self, d=None):
        dlg = tk.Toplevel(self.root)
        dlg.title("编辑日期倒计时" if d else "新建日期倒计时")
        dlg.configure(bg="white")
        dlg.transient(self.root)
        dlg.resizable(False, False)
        frm = tk.Frame(dlg, bg="white", padx=18, pady=14)
        frm.pack()
        fnt = (FONT, 10)
        today = datetime.date.today()

        if d:
            name0 = d["name"]
            y0, m0, day0 = (int(x) for x in d["target"].split("-"))
            rec0 = bool(d.get("recurring"))
        else:
            name0, rec0 = "", False
            base = today + datetime.timedelta(days=30)
            y0, m0, day0 = base.year, base.month, base.day

        tk.Label(frm, text="名称", bg="white", font=fnt).grid(row=0, column=0, sticky="e", padx=(0, 8), pady=6)
        name_ent = self._entry(frm, font=fnt, width=22)
        name_ent.grid(row=0, column=1, columnspan=2, sticky="w", pady=6, ipady=3)
        name_ent.insert(0, name0)

        tk.Label(frm, text="日期", bg="white", font=fnt).grid(row=1, column=0, sticky="e", padx=(0, 8), pady=6)
        durf = tk.Frame(frm, bg="white")
        durf.grid(row=1, column=1, columnspan=2, sticky="w", pady=6)
        sp_y = self._spinbox(durf, from_=today.year, to=today.year + 100, width=6, font=fnt, justify="center")
        sp_m = self._spinbox(durf, from_=1, to=12, width=3, font=fnt, justify="center")
        sp_d = self._spinbox(durf, from_=1, to=31, width=3, font=fnt, justify="center")
        for sp, v in ((sp_y, y0), (sp_m, m0), (sp_d, day0)):
            # Spinbox 创建时会自动填入 from_ 的值，必须先清空再写默认值，
            # 否则会出现 "00" / "20262026" 这类拼接出来的初始数字
            sp.delete(0, "end"); sp.insert(0, str(v))
        sp_y.grid(row=0, column=0, padx=2, ipady=2)
        tk.Label(durf, text="年", bg="white", font=fnt).grid(row=0, column=1, padx=(0, 8))
        sp_m.grid(row=0, column=2, padx=2, ipady=2)
        tk.Label(durf, text="月", bg="white", font=fnt).grid(row=0, column=3, padx=(0, 8))
        sp_d.grid(row=0, column=4, padx=2, ipady=2)
        tk.Label(durf, text="日", bg="white", font=fnt).grid(row=0, column=5)

        rec_var = tk.BooleanVar(value=rec0)
        tk.Checkbutton(frm, text="每年重复（适合生日、纪念日）", variable=rec_var,
                       bg="white", font=fnt, activebackground="white"
                       ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))

        tk.Label(frm, text="外观", bg="white", font=fnt).grid(row=3, column=0, sticky="ne", padx=(0, 8), pady=6)
        app_box = tk.Frame(frm, bg="white")
        app_box.grid(row=3, column=1, columnspan=2, sticky="w", pady=6)
        cur = self._appearance_editor(app_box, d, dlg)

        def confirm(event=None):
            try:
                y = int(float(sp_y.get())); m = int(float(sp_m.get())); dd = int(float(sp_d.get()))
                target = datetime.date(y, m, dd)
            except (ValueError, TypeError):
                messagebox.showwarning("日期无效", "请输入有效的年月日（例如 2 月没有 30 日）", parent=dlg)
                return
            name = name_ent.get().strip()
            if not name:
                n = sum(1 for t in self.timers if t.get("type") == "date")
                name = f"日期倒计时 {n + 1}"
            if d:
                d["name"], d["target"], d["recurring"] = name, target.isoformat(), rec_var.get()
            else:
                self.timers.append({"type": "date", "id": self.next_id, "name": name,
                                    "target": target.isoformat(), "recurring": rec_var.get(),
                                    "pinned": False})
                self.next_id += 1
            d["color"], d["image"] = cur["color"], cur["image"]
            self._save()
            self._rebuild_list()
            dlg.destroy()

        def cancel(event=None):
            dlg.destroy()

        btnf = tk.Frame(frm, bg="white")
        btnf.grid(row=4, column=0, columnspan=3, pady=(12, 0))
        self._btn(btnf, "确定", confirm, bg=GREEN, fg="white", bold=True, padx=18).pack(side="left", padx=6)
        self._btn(btnf, "取消", cancel, padx=18).pack(side="left", padx=6)

        dlg.bind("<Return>", confirm)
        dlg.bind("<Escape>", cancel)
        self._center_dialog(dlg)
        dlg.grab_set()
        name_ent.focus_set()
        dlg.wait_window()

    def _appearance_editor(self, box, t, dlg):
        """卡片外观选择区：预设色板 + 自定义颜色 + 背景图片。返回取值 dict。"""
        cur = {"color": _norm_color(t.get("color")) if t else None,
               "image": t.get("image") if t else None}
        fnt = (FONT, 9)
        swf = tk.Frame(box, bg="white")
        swf.pack(anchor="w")

        def refresh_info():
            parts = ["颜色：" + (cur["color"] or "主题默认"),
                     "图片：" + ("已设置" if cur["image"] else "无")]
            info.config(text=" · ".join(parts))

        for c in SWATCHES:
            tk.Button(swf, bg=c, width=2, relief="flat", bd=0, cursor="hand2",
                      highlightthickness=1, highlightbackground="#c9d1d9",
                      command=lambda cc=c: (cur.update(color=cc, image=None), refresh_info())
                      ).pack(side="left", padx=2, pady=2, ipady=1)

        ctl = tk.Frame(box, bg="white")
        ctl.pack(anchor="w", pady=(4, 0))

        def pick_custom():
            ret = colorchooser.askcolor(color=cur["color"] or "#ffffff", parent=dlg,
                                        title="选择卡片颜色")
            if ret and ret[1]:
                cur["color"] = _norm_color(ret[1]) or cur["color"]
                cur["image"] = None
                refresh_info()

        def pick_image():
            path = filedialog.askopenfilename(
                parent=dlg, title="选择卡片图片",
                filetypes=[("图片文件", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"), ("所有文件", "*.*")])
            if not path:
                return
            if self._card_image(os.path.abspath(path)) is None:
                messagebox.showerror("图片无法加载", "需要 Pillow 支持，请先执行：pip install pillow", parent=dlg)
                return
            cur["image"] = os.path.abspath(path)
            refresh_info()

        self._btn(ctl, "自定义颜色…", pick_custom, padx=8).pack(side="left", padx=(0, 4))
        self._btn(ctl, "默认", lambda: (cur.update(color=None, image=None), refresh_info()),
                  padx=8).pack(side="left", padx=(0, 4))
        self._btn(ctl, "选择图片…", pick_image, padx=8).pack(side="left", padx=(0, 4))
        self._btn(ctl, "清除图片", lambda: (cur.update(image=None), refresh_info()),
                  padx=8).pack(side="left")

        info = tk.Label(box, text="", bg="white", fg="#8b949e", font=(FONT, 8))
        info.pack(anchor="w", pady=(3, 0))
        refresh_info()
        return cur

    def _center_dialog(self, dlg):
        dlg.update_idletasks()
        w, h = dlg.winfo_width(), dlg.winfo_height()
        x = self.root.winfo_x() + (self.root.winfo_width() - w) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - h) // 3
        dlg.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    # ---------------- 新建 / 编辑计时 ----------------

    def _timer_dialog(self, t=None):
        dlg = tk.Toplevel(self.root)
        dlg.title("编辑计时" if t else "新建计时")
        dlg.configure(bg="white")
        dlg.transient(self.root)
        dlg.resizable(False, False)
        frm = tk.Frame(dlg, bg="white", padx=18, pady=14)
        frm.pack()
        fnt = (FONT, 10)

        tk.Label(frm, text="名称", bg="white", font=fnt).grid(row=0, column=0, sticky="e", padx=(0, 8), pady=6)
        name_ent = self._entry(frm, font=fnt, width=22)
        name_ent.grid(row=0, column=1, sticky="w", pady=6, ipady=3)
        if t:
            name_ent.insert(0, t["name"])
        tk.Label(frm, text="（留空则沿用原名 / 自动命名）", bg="white", fg="#8b949e",
                 font=(FONT, 8)).grid(row=0, column=2, sticky="w", padx=(4, 0))

        tk.Label(frm, text="时长", bg="white", font=fnt).grid(row=1, column=0, sticky="e", padx=(0, 8), pady=6)
        durf = tk.Frame(frm, bg="white")
        durf.grid(row=1, column=1, columnspan=2, sticky="w", pady=6)
        sp_h = self._spinbox(durf, from_=0, to=99, width=3, font=fnt, justify="center")
        sp_m = self._spinbox(durf, from_=0, to=59, width=3, font=fnt, justify="center")
        sp_s = self._spinbox(durf, from_=0, to=59, width=3, font=fnt, justify="center")
        if t:
            h0 = int(t["duration"]) // 3600
            m0 = int(t["duration"]) % 3600 // 60
            s0 = int(t["duration"]) % 60
        else:
            h0, m0, s0 = 0, 25, 0
        # Spinbox 创建时会自动填入 from_ 的值，必须先清空再写默认值，
        # 否则会出现 "00" / "250" 这类拼接出来的初始数字
        for sp, v in ((sp_h, str(h0)), (sp_m, str(m0)), (sp_s, str(s0))):
            sp.delete(0, "end"); sp.insert(0, v)
        sp_h.grid(row=0, column=0, padx=2, ipady=2)
        tk.Label(durf, text="时", bg="white", font=fnt).grid(row=0, column=1, padx=(0, 8))
        sp_m.grid(row=0, column=2, padx=2, ipady=2)
        tk.Label(durf, text="分", bg="white", font=fnt).grid(row=0, column=3, padx=(0, 8))
        sp_s.grid(row=0, column=4, padx=2, ipady=2)
        tk.Label(durf, text="秒", bg="white", font=fnt).grid(row=0, column=5)

        tk.Label(frm, text="外观", bg="white", font=fnt).grid(row=2, column=0, sticky="ne", padx=(0, 8), pady=6)
        app_box = tk.Frame(frm, bg="white")
        app_box.grid(row=2, column=1, columnspan=2, sticky="w", pady=6)
        cur = self._appearance_editor(app_box, t, dlg)

        def confirm(event=None):
            try:
                h = int(float(sp_h.get() or 0))
                m = int(float(sp_m.get() or 0))
                s = int(float(sp_s.get() or 0))
            except ValueError:
                messagebox.showwarning("时长无效", "时 / 分 / 秒 请输入数字", parent=dlg)
                return
            total = h * 3600 + m * 60 + s
            if total <= 0:
                messagebox.showwarning("时长无效", "时长必须大于 0 秒", parent=dlg)
                return
            if t:
                self._apply_timer_edit(t, name_ent.get().strip(), total)
            else:
                name = name_ent.get().strip() or f"倒计时 {sum(1 for x in self.timers if x.get('type') != 'date') + 1}"
                self.timers.append({"type": "timer", "id": self.next_id, "name": name,
                                    "duration": float(total), "remaining": float(total),
                                    "base": float(total), "since": None, "state": IDLE})
                self.next_id += 1
            t["color"], t["image"] = cur["color"], cur["image"]
            self._save()
            self._rebuild_list()
            dlg.destroy()

        def cancel(event=None):
            dlg.destroy()

        btnf = tk.Frame(frm, bg="white")
        btnf.grid(row=3, column=0, columnspan=3, pady=(10, 0))
        self._btn(btnf, "确定", confirm, bg=BLUE, fg="white", bold=True, padx=18).pack(side="left", padx=6)
        self._btn(btnf, "取消", cancel, padx=18).pack(side="left", padx=6)

        dlg.bind("<Return>", confirm)
        dlg.bind("<Escape>", cancel)
        self._center_dialog(dlg)
        dlg.grab_set()
        name_ent.focus_set()
        dlg.wait_window()

    def _apply_timer_edit(self, t, name, total):
        """应用对计时的编辑：只改名保留进度；时长变化则重置为未开始并从头计时。"""
        if not name:
            name = t["name"]
        t["name"] = name
        if float(total) != t["duration"]:
            t["duration"] = float(total)
            t["remaining"] = float(total)
            t["base"] = float(total)
            t["since"] = None
            t["state"] = IDLE

    def toggle_pin(self, d):
        d["pinned"] = not d.get("pinned", False)
        self._save()
        self._rebuild_list()

    # ---------------- 设置 ----------------

    def _settings_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("设置")
        dlg.configure(bg="white")
        dlg.transient(self.root)
        dlg.resizable(False, False)
        frm = tk.Frame(dlg, bg="white", padx=18, pady=14)
        frm.pack()
        fnt = (FONT, 10)
        s = dict(self.settings)

        top_var = tk.BooleanVar(value=bool(s.get("topmost")))
        auto_var = tk.BooleanVar(value=autostart_enabled())
        theme_var = tk.StringVar(value=s.get("theme", "glass"))
        op_var = tk.DoubleVar(value=float(s.get("opacity", 0.9)))

        tk.Label(frm, text="窗口", bg="white", fg="#1f2328", font=(FONT, 10, "bold")
                 ).grid(row=0, column=0, sticky="nw", padx=(0, 12), pady=(0, 4))
        box1 = tk.Frame(frm, bg="white")
        box1.grid(row=0, column=1, sticky="w")
        tk.Checkbutton(box1, text="置顶到所有应用最上层", variable=top_var, bg="white",
                       font=fnt, activebackground="white").pack(anchor="w")
        tk.Checkbutton(box1, text="开机自启动", variable=auto_var, bg="white",
                       font=fnt, activebackground="white").pack(anchor="w")

        tk.Label(frm, text="背景", bg="white", fg="#1f2328", font=(FONT, 10, "bold")
                 ).grid(row=1, column=0, sticky="nw", padx=(0, 12), pady=(8, 0))
        box2 = tk.Frame(frm, bg="white")
        box2.grid(row=1, column=1, sticky="w", pady=(8, 0))
        for val, txt in (("glass", "毛玻璃透明（推荐，Win11）"), ("alpha", "半透明"), ("solid", "不透明")):
            tk.Radiobutton(box2, text=txt, variable=theme_var, value=val, bg="white",
                           font=fnt, activebackground="white").pack(anchor="w")
        opf = tk.Frame(box2, bg="white")
        opf.pack(anchor="w", pady=(2, 0))
        tk.Label(opf, text="半透明时透明度：", bg="white", font=(FONT, 9)).pack(side="left")
        tk.Scale(opf, variable=op_var, from_=0.70, to=1.0, resolution=0.05,
                 orient="horizontal", length=160, bg="white", highlightthickness=0).pack(side="left")

        def confirm(event=None):
            old_auto = autostart_enabled()
            s.update({"theme": theme_var.get(), "opacity": round(float(op_var.get()), 2),
                      "topmost": bool(top_var.get())})
            self.settings = s
            save_settings(s)
            want_auto = bool(auto_var.get())
            if want_auto != old_auto:
                if not set_autostart(want_auto):
                    messagebox.showwarning("自启动设置失败", "写入注册表失败，请检查权限。", parent=dlg)
            self._rebuild_ui()
            dlg.destroy()

        def cancel(event=None):
            dlg.destroy()

        btnf = tk.Frame(frm, bg="white")
        btnf.grid(row=2, column=0, columnspan=2, pady=(14, 0))
        self._btn(btnf, "确定", confirm, bg=BLUE, fg="white", bold=True, padx=18).pack(side="left", padx=6)
        self._btn(btnf, "取消", cancel, padx=18).pack(side="left", padx=6)

        dlg.bind("<Return>", confirm)
        dlg.bind("<Escape>", cancel)
        self._center_dialog(dlg)
        dlg.grab_set()
        dlg.wait_window()

    # ---------------- 计时逻辑 ----------------

    def cur_remaining(self, t):
        if t["state"] == RUNNING:
            return max(0.0, t["base"] - (time_mod.monotonic() - t["since"]))
        return t["remaining"]

    @staticmethod
    def _freeze(t):
        """把运行中的计时按当前时刻冻结到 remaining。"""
        t["remaining"] = max(0.0, t["base"] - (time_mod.monotonic() - t["since"]))
        t["since"] = None

    def start(self, t):
        if t["state"] == RUNNING:
            return
        for o in self.timers:          # 启动新的之前，先暂停正在计时的
            if o is not t and o.get("type") != "date" and o["state"] == RUNNING:
                self._freeze(o)
                o["state"] = PAUSED
        if t["state"] == DONE:         # 已完成的重新开始 = 从头计时
            t["remaining"] = t["duration"]
        t["base"] = t["remaining"]
        t["since"] = time_mod.monotonic()
        t["state"] = RUNNING
        self._save()
        self._rebuild_list()

    def pause(self, t):
        if t["state"] != RUNNING:
            return
        self._freeze(t)
        t["state"] = PAUSED
        self._save()
        self._rebuild_list()

    def reset(self, t):
        t["remaining"] = t["duration"]
        t["base"] = t["duration"]
        t["since"] = None
        t["state"] = IDLE
        self._save()
        self._rebuild_list()

    def delete(self, t):
        if not messagebox.askyesno("删除倒计时", f"确定删除「{t['name']}」吗？"):
            return
        self.timers.remove(t)
        self._save()
        self._rebuild_list()

    @staticmethod
    def _reset_timer(t):
        t["remaining"] = t["duration"]
        t["base"] = t["duration"]
        t["since"] = None
        t["state"] = IDLE

    def _check_day_rollover(self):
        """跨天时把所有计时倒计时重置（每日自动重置）。"""
        today = datetime.date.today()
        if today == self._today:
            return False
        self._today = today
        changed = False
        for t in self.timers:
            if t.get("type") != "date" and t["state"] != IDLE:
                self._reset_timer(t)
                changed = True
        if changed:
            self._status_hold = time_mod.monotonic() + 8
            self.status.config(text="🌅 新的一天，所有计时已重置")
            self._save()
            self._rebuild_list()
        return changed

    def _finish(self, t):
        t["remaining"] = 0.0
        t["base"] = 0.0
        t["since"] = None
        t["state"] = DONE
        self._save()
        self._rebuild_list()
        self._status_hold = time_mod.monotonic() + 8
        self.status.config(text=f"⏰ 「{t['name']}」时间到！")
        threading.Thread(target=self._beep, daemon=True).start()
        try:
            self.root.attributes("-topmost", True)
            self.root.after(2000, lambda: self.root.attributes("-topmost", self._topmost))
        except tk.TclError:
            pass

    def _beep(self):
        if self.silent:
            return
        try:
            import winsound
            for freq in (1046, 1318, 1568):
                winsound.Beep(freq, 250)
            time_mod.sleep(0.15)
            for freq in (1568, 1318, 1046):
                winsound.Beep(freq, 180)
        except Exception:
            try:
                self.root.bell()
            except Exception:
                pass

    def _tick_once(self):
        running = None
        for t in self.timers:
            if t.get("type") != "date" and t["state"] == RUNNING:
                rem = self.cur_remaining(t)
                row = self.rows.get(t["id"])
                if row and row.get("time") is not None:
                    row["cv"].itemconfig(row["time"], text=fmt(rem))
                    self._draw_prog(t)
                if rem <= 0:
                    self._finish(t)
                else:
                    running = t
        now = time_mod.monotonic()
        if now - self._date_refresh >= 30:
            self._date_refresh = now
            self._refresh_date_rows()
            self._check_day_rollover()
        if running is not None:
            rem = self.cur_remaining(running)
            self.root.title(f"▶ {running['name']}  {fmt(rem)} — 多倒计时器")
            if now >= self._status_hold:
                self.status.config(text=f"正在计时：「{running['name']}」，剩余 {fmt(rem)}")
        else:
            self.root.title("多倒计时器")
            if now >= self._status_hold:
                tn = sum(1 for t in self.timers if t.get("type") != "date")
                done = sum(1 for t in self.timers if t.get("type") != "date" and t["state"] == DONE)
                dn = len(self.timers) - tn
                parts = []
                if tn:
                    parts.append(f"共 {tn} 个计时（{done} 个已完成）")
                if dn:
                    parts.append(f"{dn} 个日期倒计时")
                tip = " · 双击卡片可编辑" if (tn or dn) else ""
                self.status.config(text=("，".join(parts) if parts else "点击右上角「＋ 计时」或「＋ 日期」添加") + tip)

    def _tick(self):
        self._tick_once()
        self.root.after(100, self._tick)

    # ---------------- 保存 / 加载 ----------------

    def _save(self):
        data = []
        for t in self.timers:
            if t.get("type") == "date":
                data.append({"type": "date", "id": t["id"], "name": t["name"],
                             "target": t["target"], "recurring": bool(t.get("recurring")),
                             "pinned": bool(t.get("pinned")),
                             "color": t.get("color"), "image": t.get("image")})
                continue
            state = PAUSED if t["state"] == RUNNING else t["state"]
            data.append({"type": "timer", "id": t["id"], "name": t["name"],
                         "duration": t["duration"], "remaining": self.cur_remaining(t),
                         "state": state, "color": t.get("color"), "image": t.get("image")})
        try:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump({"day": datetime.date.today().isoformat(),
                           "next_id": self.next_id, "timers": data}, f,
                          ensure_ascii=False, indent=2)
        except OSError:
            pass

    def _load(self):
        if not os.path.exists(DATA_FILE):
            return
        try:
            with open(DATA_FILE, encoding="utf-8") as f:
                data = json.load(f)
            for d in data.get("timers", []):
                try:
                    color = _norm_color(d.get("color"))
                    image = d.get("image")
                    image = image if isinstance(image, str) and os.path.exists(image) else None
                    if d.get("type") == "date":
                        target = datetime.date.fromisoformat(d["target"])
                        self.timers.append({"type": "date", "id": int(d["id"]),
                                            "name": d.get("name", "日期倒计时"),
                                            "target": target.isoformat(),
                                            "recurring": bool(d.get("recurring", False)),
                                            "pinned": bool(d.get("pinned", False)),
                                            "color": color, "image": image})
                    else:
                        state = d.get("state", IDLE)
                        if state not in (IDLE, PAUSED, DONE):
                            state = IDLE
                        rem = min(float(d["duration"]), float(d.get("remaining", d["duration"])))
                        self.timers.append({"type": "timer", "id": int(d["id"]),
                                            "name": d.get("name", "倒计时"),
                                            "duration": float(d["duration"]), "remaining": rem,
                                            "base": rem, "since": None, "state": state,
                                            "color": color, "image": image})
                except (ValueError, KeyError, TypeError):
                    continue
            max_id = max((t["id"] for t in self.timers), default=0)
            self.next_id = max(int(data.get("next_id", 1)), max_id + 1)
            saved_day = data.get("day")
            if saved_day is not None and saved_day != datetime.date.today().isoformat():
                for t in self.timers:      # 新的一天：所有计时恢复满时长
                    if t.get("type") != "date" and t["state"] != IDLE:
                        self._reset_timer(t)
        except (OSError, ValueError, KeyError, TypeError):
            self.timers = []

    def _on_close(self):
        self._save()
        self.root.destroy()


def ttk_scrollbar(holder, canvas):
    from tkinter import ttk
    return ttk.Scrollbar(holder, orient="vertical", command=canvas.yview)


def _selftest():
    import tempfile
    global DATA_FILE, SETTINGS_FILE
    DATA_FILE = os.path.join(tempfile.gettempdir(), "multi_timer_selftest.json")
    SETTINGS_FILE = os.path.join(tempfile.gettempdir(), "multi_timer_settings_test.json")
    for p in (DATA_FILE, SETTINGS_FILE):
        if os.path.exists(p):
            os.remove(p)

    assert fmt(0) == "00:00"
    assert fmt(65) == "01:05"
    assert fmt(3661) == "1:01:01"
    assert _mix("#ffffff", "#000000", 0.5) == "#808080"
    assert _lum("#ffffff") > _lum("#000000")
    assert _norm_color(MAGIC) == "#020202"         # 避开透明键色
    assert _norm_color("#000000") == "#000000"     # 纯黑与键色不同，允许
    assert _norm_color("red") is None

    s = dict(DEFAULT_SETTINGS); s["opacity"] = 0.75
    save_settings(s)
    assert load_settings()["opacity"] == 0.75

    # Spinbox 修复回归：创建时自动填 from_ 值，必须先 delete 再 insert
    probe = tk.Tk()
    probe.withdraw()
    sp = tk.Spinbox(probe, from_=0, to=59)
    assert sp.get() == "0", "Spinbox 应自动填入 from_ 值"
    sp.delete(0, "end"); sp.insert(0, "25")
    assert sp.get() == "25"
    probe.destroy()

    root = tk.Tk()
    root.withdraw()
    app = TimerApp(root)
    app.silent = True

    def mk(i, name, dur):
        return {"type": "timer", "id": i, "name": name, "duration": float(dur),
                "remaining": float(dur), "base": float(dur), "since": None, "state": IDLE}

    app.timers = [mk(1, "A", 100), mk(2, "B", 100)]
    app.next_id = 3
    app._rebuild_list()

    app.start(app.timers[0])
    assert app.timers[0]["state"] == RUNNING
    root.update()

    app.start(app.timers[1])
    assert app.timers[0]["state"] == PAUSED, "启动 B 应自动暂停 A"
    assert app.timers[1]["state"] == RUNNING

    time_mod.sleep(0.25)
    rem_a = app.cur_remaining(app.timers[0])
    assert 97 <= rem_a <= 100, rem_a

    app.timers[1]["since"] -= 101  # 快进，让 B 超时
    app._tick_once()
    assert app.timers[1]["state"] == DONE and app.timers[1]["remaining"] == 0

    app.start(app.timers[1])       # 已完成的重新开始 = 从头计时
    assert app.timers[1]["state"] == RUNNING and abs(app.timers[1]["remaining"] - 100) < 1

    app.reset(app.timers[1])
    assert app.timers[1]["state"] == IDLE and app.timers[1]["remaining"] == 100

    # 日期倒计时
    today = datetime.date.today()
    d1 = {"type": "date", "id": 3, "name": "考研", "recurring": False, "pinned": False,
          "target": (today + datetime.timedelta(days=10)).isoformat()}
    d2 = {"type": "date", "id": 4, "name": "生日", "recurring": True, "pinned": False,
          "target": (today - datetime.timedelta(days=365)).isoformat()}
    d3 = {"type": "date", "id": 5, "name": "旧事", "recurring": False, "pinned": False,
          "target": (today - datetime.timedelta(days=3)).isoformat()}
    app.timers += [d1, d2, d3]
    app.next_id = 6
    app._rebuild_list()
    assert app._days_left(d1) == 10
    assert app._days_left(d3) == -3
    assert app._days_left(d2) in (0, 1)   # 往年今天 → 自动滚到下一个生日

    app.start(app.timers[0])
    time_mod.sleep(0.1)
    app._save()
    with open(DATA_FILE, encoding="utf-8") as f:
        data = json.load(f)
    st = {x["name"]: x for x in data["timers"]}
    assert len(data["timers"]) == 5
    assert st["A"]["state"] == PAUSED            # 正在计时的保存后转为暂停
    assert st["A"]["type"] == "timer" and st["考研"]["type"] == "date"
    assert st["生日"]["recurring"] is True

    # 旧格式兼容（无 type 字段）
    legacy = {"next_id": 9, "timers": [{"id": 9, "name": "旧", "duration": 60,
                                        "remaining": 60, "state": "已暂停"}]}
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(legacy, f)
    app.timers = []
    app._load()
    assert len(app.timers) == 1 and app.timers[0]["type"] == "timer"
    assert app.timers[0]["duration"] == 60 and app.next_id == 10

    # 编辑计时：只改名保留进度；改时长重置为未开始
    t0 = {"type": "timer", "id": 7, "name": "旧名", "duration": 100.0, "remaining": 40.0,
          "base": 40.0, "since": None, "state": PAUSED}
    app.timers = [t0]
    app._apply_timer_edit(t0, "新名", 100)
    assert t0["name"] == "新名" and t0["remaining"] == 40 and t0["state"] == PAUSED
    app._apply_timer_edit(t0, "新名", 200)
    assert t0["duration"] == 200 and t0["remaining"] == 200 and t0["state"] == IDLE

    # 日期置顶：置顶的固定在窗口顶部（滚动区外的固定面板），同区按剩余天数
    far = {"type": "date", "id": 8, "name": "远", "recurring": False, "pinned": True,
           "target": (today + datetime.timedelta(days=50)).isoformat()}
    near = {"type": "date", "id": 9, "name": "近", "recurring": False, "pinned": False,
            "target": (today + datetime.timedelta(days=5)).isoformat()}
    app.timers = [near, far]
    app.next_id = 10
    app._rebuild_list()

    assert [x["name"] for x in app._sections()[0]] == ["远"], "置顶区应在最顶"
    assert [x["name"] for x in app._sections()[2]] == ["近"]
    app.toggle_pin(near)
    assert near["pinned"] is True
    assert [x["name"] for x in app._sections()[0]] == ["近", "远"]
    assert app._sections()[2] == []
    app._save()
    with open(DATA_FILE, encoding="utf-8") as f:
        data = json.load(f)
    pd_ = {x["name"]: x for x in data["timers"]}
    assert pd_["远"]["pinned"] is True and pd_["近"]["pinned"] is True

    # 每日自动重置：跨天加载重置、同天保留进度、运行中跨天重置
    yesterday = (today - datetime.timedelta(days=1)).isoformat()
    old = {"day": yesterday, "next_id": 20, "timers": [
        {"type": "timer", "id": 20, "name": "昨天", "duration": 300,
         "remaining": 120, "state": "已暂停"}]}
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(old, f)
    app.timers = []
    app._load()
    assert app.timers[0]["state"] == IDLE and app.timers[0]["remaining"] == 300

    same = {"day": today.isoformat(), "next_id": 21, "timers": [
        {"type": "timer", "id": 21, "name": "今天", "duration": 300,
         "remaining": 120, "state": "已暂停"}]}
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(same, f)
    app.timers = []
    app._load()
    assert app.timers[0]["state"] == PAUSED and app.timers[0]["remaining"] == 120

    app.timers = [{"type": "timer", "id": 30, "name": "跑着", "duration": 300.0,
                   "remaining": 150.0, "base": 150.0, "since": time_mod.monotonic(),
                   "state": RUNNING}]
    app._today = today - datetime.timedelta(days=1)
    assert app._check_day_rollover() is True
    assert app.timers[0]["state"] == IDLE and app.timers[0]["remaining"] == 300
    assert app._check_day_rollover() is False   # 同一天再查不再动

    # 卡片外观：颜色/图片字段持久化；失效图片路径加载时丢弃
    styled = {"day": today.isoformat(), "next_id": 40, "timers": [
        {"type": "timer", "id": 40, "name": "花哨", "duration": 60, "remaining": 60,
         "state": "未开始", "color": "#ffe3e3", "image": "Z:/不存在的图.png"}]}
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(styled, f)
    app.timers = []
    app._load()
    assert app.timers[0]["color"] == "#ffe3e3" and app.timers[0]["image"] is None
    pal = app._card_pal(app.timers[0])
    assert pal["card"] == "#ffe3e3" and not pal["img"]
    app.timers[0]["image"] = None
    app.timers[0]["color"] = "#212f3d"
    pal2 = app._card_pal(app.timers[0])
    assert pal2["custom"] and _lum(pal2["card"]) < 140 and pal2["text"] == "#f3f6fc"

    # 弹窗构建冒烟测试：三个对话框必须能完整创建
    # （曾因把 Spinbox 误写成 Entry，创建时抛 TclError，弹窗只画出一半）
    def close_dialogs():
        for w in root.winfo_children():
            if isinstance(w, tk.Toplevel):
                w.destroy()

    app.timers.append({"type": "date", "id": 41, "name": "日期", "target": today.isoformat(),
                       "recurring": False, "pinned": False, "color": None, "image": None})
    root.after(10, close_dialogs)
    app._timer_dialog()
    root.after(10, close_dialogs)
    app._timer_dialog(app.timers[0])       # 编辑模式
    root.after(10, close_dialogs)
    app._date_dialog()
    root.after(10, close_dialogs)
    app._date_dialog(app.timers[1])        # 编辑模式
    root.after(10, close_dialogs)
    app._settings_dialog()

    root.destroy()
    for p in (DATA_FILE, SETTINGS_FILE):
        if os.path.exists(p):
            os.remove(p)
    print("SELFTEST OK")


def main():
    if "--selftest" in sys.argv:
        _selftest()
        return
    root = tk.Tk()
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    TimerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
