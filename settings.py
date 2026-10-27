"""Settings store + the tkinter settings window for the bubble cat.

The settings window runs in its own thread and never touches the Win32 pet
window directly: every change is handed to the pet through callbacks, which
the pet turns into messages on its own UI queue.
"""

from __future__ import annotations

import sys
import threading
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, ttk

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / "vendor"))
sys.path.insert(0, str(BASE))

from PIL import Image, ImageTk  # noqa: E402

import sprite  # noqa: E402

# ---- palette --------------------------------------------------------------
BG = "#FBF6EC"
PANEL = "#FFF9F0"
FG = "#4A3A31"
MUTED = "#8C7A6C"
ACCENT = "#C98F5F"
ACCENT_DARK = "#A97044"
BORDER = "#E4D5C3"

MODEL_CHOICES = [(key, skin.name) for key, skin in sprite.SKINS.items()]
MODEL_CHOICES.append(("custom", "自定义图片"))

SETTING_KEYS = (
    "model", "custom_image", "pet_scale", "opacity", "speed", "auto_cutout",
    "roam", "follow_mouse", "click_feed", "auto_actions", "topmost",
)


@dataclass
class Settings:
    model: str = "cream_cat"
    custom_image: str = ""
    pet_scale: float = 1.0
    opacity: float = 1.0
    speed: float = 1.0
    auto_cutout: bool = True
    roam: bool = True
    follow_mouse: bool = False
    click_feed: bool = False
    auto_actions: bool = True
    topmost: bool = True

    @classmethod
    def from_dict(cls, data: dict | None) -> "Settings":
        data = data or {}
        s = cls()
        model = str(data.get("model", s.model))
        s.model = model if (model in sprite.SKINS or model == "custom") else s.model
        s.custom_image = str(data.get("custom_image", "") or "")
        if s.model == "custom" and not s.custom_image:
            s.model = "cream_cat"
        s.pet_scale = _clamp(float(data.get("pet_scale", 1.0) or 1.0), 0.6, 1.8)
        s.opacity = _clamp(float(data.get("opacity", 1.0) or 1.0), 0.35, 1.0)
        s.speed = _clamp(float(data.get("speed", 1.0) or 1.0), 0.5, 1.8)
        for key in ("auto_cutout", "roam", "follow_mouse", "click_feed",
                    "auto_actions", "topmost"):
            setattr(s, key, bool(data.get(key, getattr(s, key))))
        return s

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in SETTING_KEYS}

    def update_from(self, data: dict) -> None:
        for key, value in (data or {}).items():
            if key in SETTING_KEYS:
                setattr(self, key, value)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


class SettingsWindow:
    """A single settings window living in its own thread."""

    def __init__(self, snapshot, on_change, on_action, on_command,
                 dpi_scale: float = 1.0):
        self._snapshot = snapshot
        self._on_change = on_change
        self._on_action = on_action
        self._on_command = on_command
        self._dpi = max(1.0, min(2.0, dpi_scale))
        self._stop = threading.Event()
        self.closed = False
        self.root: tk.Tk | None = None
        self._custom_img: Image.Image | None = None
        self._custom_src: Image.Image | None = None
        self._pending: dict = {}
        self._flush_job = None
        self._photo = None
        self._slider_labels: dict = {}
        self._thread = threading.Thread(target=self._run, name="pet-settings",
                                        daemon=True)

    # ------------------------------------------------------------------ api -
    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._stop.set()

    # --------------------------------------------------------------- thread -
    def _run(self) -> None:
        try:
            self.root = tk.Tk()
            self.root.title("泡泡猫 · 设置")
            self.root.configure(bg=BG)
            if self._dpi != 1.0:
                try:
                    self.root.tk.call("tk", "scaling", 1.333 * self._dpi)
                except Exception:
                    pass
            self._style()
            self._build()
            self.root.protocol("WM_DELETE_WINDOW", self._on_close)
            self._load_current()
            self.root.update_idletasks()
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            w = max(480, self.root.winfo_reqwidth())
            h = min(self.root.winfo_reqheight(), sh - 120)
            self.root.geometry(f"{w}x{h}+{max(20, sw - w - 40)}+80")
            self.root.attributes("-topmost", True)
            self._tick_status()
            self.root.mainloop()
        except Exception:
            pass
        finally:
            self.closed = True

    def _style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=BG, foreground=FG,
                        font=("Microsoft YaHei UI", 10))
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED,
                        font=("Microsoft YaHei UI", 9))
        style.configure("Title.TLabel", background=BG, foreground=FG,
                        font=("Microsoft YaHei UI", 13, "bold"))
        style.configure("TCheckbutton", background=BG, foreground=FG)
        style.map("TCheckbutton", background=[("active", BG)])
        style.configure("TButton", padding=(10, 5), background="#F3E6D5",
                        bordercolor=BORDER, focuscolor=BG)
        style.map("TButton", background=[("active", "#EBD8C0")])
        style.configure("Accent.TButton", background=ACCENT, foreground="white",
                        padding=(10, 5), borderwidth=0)
        style.map("Accent.TButton", background=[("active", ACCENT_DARK)])
        style.configure("TCombobox", padding=4)
        style.configure("TSeparator", background=BORDER)

    def _build(self) -> None:
        root = self.root
        pad = {"padx": 18}
        ttk.Label(root, text="泡泡猫 · 设置", style="Title.TLabel").pack(
            anchor="w", pady=(14, 2), **pad)
        ttk.Label(root, text="改完立刻生效，也会自动保存", style="Muted.TLabel").pack(
            anchor="w", pady=(0, 2), **pad)
        ttk.Label(root, text="Ctrl+Alt+S 设置 · Ctrl+Alt+D 跳舞 · Ctrl+Alt+F 投喂",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 8), **pad)

        # ---- model row ----
        model_row = ttk.Frame(root)
        model_row.pack(fill="x", **pad)
        ttk.Label(model_row, text="宠物模型").pack(side="left")
        self.model_var = tk.StringVar()
        self.model_box = ttk.Combobox(model_row, textvariable=self.model_var,
                                      state="readonly", width=12,
                                      values=[name for _, name in MODEL_CHOICES])
        self.model_box.pack(side="left", padx=(10, 8))
        self.model_box.bind("<<ComboboxSelected>>", self._on_model_selected)
        ttk.Button(model_row, text="自定义图片…", command=self._pick_image).pack(
            side="left")
        self.custom_label = ttk.Label(root, text="", style="Muted.TLabel")
        self.custom_label.pack(anchor="w", padx=18, pady=(2, 6))

        # ---- body: preview on the left, sliders + toggles on the right ----
        body = ttk.Frame(root)
        body.pack(fill="both", expand=True, padx=18)

        left = tk.Frame(body, bg=PANEL, highlightbackground=BORDER,
                        highlightthickness=1)
        left.pack(side="left", fill="y")
        self.preview = tk.Label(left, bg=PANEL, width=170, height=225)
        self.preview.pack(padx=6, pady=6)

        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(14, 0))

        self.scale_var = tk.DoubleVar(value=1.0)
        self.opacity_var = tk.DoubleVar(value=1.0)
        self.speed_var = tk.DoubleVar(value=1.0)
        self._slider(right, "大小", self.scale_var, 0.6, 1.8, self._fmt_pct)
        self._slider(right, "透明度", self.opacity_var, 0.35, 1.0, self._fmt_pct)
        self._slider(right, "走路速度", self.speed_var, 0.5, 1.8, self._fmt_pct)

        ttk.Separator(right).pack(fill="x", pady=(8, 4))

        self.toggle_vars = {
            "roam": tk.BooleanVar(value=True),
            "follow_mouse": tk.BooleanVar(value=False),
            "click_feed": tk.BooleanVar(value=False),
            "auto_actions": tk.BooleanVar(value=True),
            "auto_cutout": tk.BooleanVar(value=True),
            "topmost": tk.BooleanVar(value=True),
        }
        labels = (
            ("roam", "自由漫游 —— 偶尔散散步"),
            ("follow_mouse", "跟随鼠标 —— 黏在光标旁"),
            ("click_feed", "单击桌面投喂 —— 点哪掉哪"),
            ("auto_actions", "自动表演 —— 跳舞/蹦跳"),
            ("auto_cutout", "自定义图自动去白底"),
            ("topmost", "窗口置顶"),
        )
        for key, text in labels:
            ttk.Checkbutton(right, text=text, variable=self.toggle_vars[key],
                            command=lambda k=key: self._on_toggle(k)).pack(
                anchor="w", pady=0)

        # ---- actions ----
        ttk.Separator(root).pack(fill="x", padx=18, pady=(10, 6))
        ttk.Label(root, text="让它表演一下").pack(anchor="w", padx=18)
        act = ttk.Frame(root)
        act.pack(fill="x", padx=14, pady=(4, 0))
        for text, name in (("跳舞", "dance"), ("转圈", "spin"),
                           ("蹦一蹦", "hop"), ("打滚", "roll")):
            ttk.Button(act, text=text, style="Accent.TButton",
                       command=lambda n=name: self._on_action(n)).pack(
                side="left", expand=True, fill="x", padx=3)
        ttk.Button(root, text="投喂一块小饼干",
                   command=lambda: self._on_command("feed")).pack(
            fill="x", padx=18, pady=(6, 0))

        # ---- footer ----
        ttk.Separator(root).pack(fill="x", padx=18, pady=(10, 6))
        foot = ttk.Frame(root)
        foot.pack(fill="x", padx=18)
        ttk.Button(foot, text="回到右下角", command=lambda: self._on_command("home")).pack(
            side="left", expand=True, fill="x", padx=3)
        ttk.Button(foot, text="恢复默认", command=self._reset).pack(
            side="left", expand=True, fill="x", padx=3)
        ttk.Button(foot, text="退出宠物", style="Accent.TButton",
                   command=lambda: self._on_command("quit")).pack(
            side="left", expand=True, fill="x", padx=3)
        self.status = ttk.Label(root, text="", style="Muted.TLabel")
        self.status.pack(anchor="w", padx=18, pady=(8, 12))

    def _slider(self, root, title, var, lo, hi, fmt) -> None:
        box = ttk.Frame(root)
        box.pack(fill="x", pady=(6, 0))
        top = ttk.Frame(box)
        top.pack(fill="x")
        ttk.Label(top, text=title).pack(side="left")
        value_label = ttk.Label(top, text=fmt(var.get()), style="Muted.TLabel")
        value_label.pack(side="right")

        def changed(value, target=var, label=value_label):
            target.set(round(float(value), 2))
            label.configure(text=fmt(target.get()))
            self._queue()

        ttk.Scale(box, from_=lo, to=hi, variable=var,
                  command=changed).pack(fill="x")
        self._slider_labels[title] = value_label

    @staticmethod
    def _fmt_pct(value: float) -> str:
        return f"{int(round(value * 100))}%"

    # --------------------------------------------------------------- helpers
    def _current_model_key(self) -> str:
        name = self.model_var.get()
        for key, label in MODEL_CHOICES:
            if label == name:
                return key
        return "cream_cat"

    def _load_current(self) -> None:
        snap = self._snapshot() or {}
        settings = snap.get("settings", {})
        self._apply_to_widgets(settings)
        if self._current_model_key() == "custom":
            path = str(settings.get("custom_image", "") or "")
            if path:
                self._load_custom(path)
        self._render_preview()

    def _apply_to_widgets(self, settings: dict) -> None:
        model = settings.get("model", "cream_cat")
        label = dict(MODEL_CHOICES).get(model, "奶油猫")
        self.model_var.set(label)
        self.scale_var.set(float(settings.get("pet_scale", 1.0)))
        self.opacity_var.set(float(settings.get("opacity", 1.0)))
        self.speed_var.set(float(settings.get("speed", 1.0)))
        for key, var in self.toggle_vars.items():
            var.set(bool(settings.get(key, var.get())))
        path = str(settings.get("custom_image", "") or "")
        self.custom_label.configure(
            text=("当前图片：" + Path(path).name) if path else
            "把 PNG / JPG 图片当作宠物（建议透明背景）")
        self._refresh_slider_labels()

    def _refresh_slider_labels(self) -> None:
        for title, var in (("大小", self.scale_var), ("透明度", self.opacity_var),
                           ("走路速度", self.speed_var)):
            label = getattr(self, "_slider_labels", {}).get(title)
            if label is not None:
                label.configure(text=self._fmt_pct(var.get()))

    def _render_preview(self) -> None:
        key = self._current_model_key()
        try:
            img = sprite.preview_model(key, self._custom_img, scale=0.62)
            self._photo = ImageTk.PhotoImage(img)
            self.preview.configure(image=self._photo, width=img.width,
                                   height=img.height)
        except Exception:
            self.preview.configure(image="", text="预览不可用")

    def _load_custom(self, path: str) -> bool:
        try:
            im = Image.open(path).convert("RGBA")
            im.thumbnail((720, 720), Image.LANCZOS)
            self._custom_src = im
            self._custom_img = (sprite.cutout_white(im)
                                if self.toggle_vars["auto_cutout"].get() else im)
            return True
        except Exception:
            self._custom_img = None
            self._custom_src = None
            return False

    # -------------------------------------------------------------- handlers
    def _queue(self, extra: dict | None = None) -> None:
        if extra:
            self._pending.update(extra)
        if self._flush_job is not None:
            try:
                self.root.after_cancel(self._flush_job)
            except Exception:
                pass
        self._flush_job = self.root.after(180, self._flush)

    def _flush(self) -> None:
        self._flush_job = None
        data, self._pending = self._pending, {}
        try:
            self._on_change(data)
        except Exception:
            pass

    def _on_model_selected(self, _event=None) -> None:
        key = self._current_model_key()
        if key == "custom" and self._custom_img is None:
            path = filedialog.askopenfilename(
                title="选择宠物图片",
                filetypes=[("图片", "*.png *.jpg *.jpeg *.webp *.gif"),
                           ("所有文件", "*.*")])
            if not path or not self._load_custom(path):
                self.model_var.set("奶油猫")
                return
            self.custom_label.configure(text="当前图片：" + Path(path).name)
            self._queue({"model": "custom", "custom_image": path})
        else:
            self._queue({"model": key})
        self._render_preview()

    def _pick_image(self) -> None:
        path = filedialog.askopenfilename(
            title="选择宠物图片",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.webp *.gif"),
                       ("所有文件", "*.*")])
        if not path:
            return
        if not self._load_custom(path):
            self.custom_label.configure(text="这张图片打不开，换一张试试")
            return
        self.model_var.set("自定义图片")
        self.custom_label.configure(text="当前图片：" + Path(path).name)
        self._queue({"model": "custom", "custom_image": path})
        self._render_preview()

    def _on_toggle(self, key: str) -> None:
        self._queue({key: bool(self.toggle_vars[key].get())})
        if key == "auto_cutout" and self._custom_src is not None:
            self._custom_img = (sprite.cutout_white(self._custom_src)
                                if self.toggle_vars[key].get() else self._custom_src)
            self._render_preview()

    def _reset(self) -> None:
        defaults = Settings()
        self._apply_to_widgets(defaults.to_dict())
        self._queue(defaults.to_dict())
        self._render_preview()

    def _tick_status(self) -> None:
        if self._stop.is_set():
            self._shutdown()
            return
        try:
            snap = self._snapshot() or {}
            hunger = int(snap.get("hunger", 0))
            mood = int(snap.get("mood", 0))
            self.status.configure(
                text=f"饱食度 {hunger}%　心情 {mood}%　"
                     f"{snap.get('mode_text', '')}")
        except Exception:
            pass
        try:
            self.root.after(600, self._tick_status)
        except Exception:
            pass

    def _on_close(self) -> None:
        self._shutdown()

    def _shutdown(self) -> None:
        if self.root is None:
            return
        try:
            self.root.destroy()
        except Exception:
            pass
        self.closed = True


__all__ = ["Settings", "SettingsWindow", "MODEL_CHOICES", "SETTING_KEYS"]
