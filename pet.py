"""泡泡猫 - a small, controllable Windows desktop pet.

Left click the cat: a snack appears beside it and it walks over to eat.
Right click: menu (follow mouse, free roam, click-anywhere-to-feed, sleep...).
Drag with the left button: put it anywhere on screen.
Ctrl+Alt+F: drop a snack at the mouse cursor.

Everything is drawn with Pillow into a per-pixel-alpha layered window, so the
pet is smooth and its transparent area never blocks clicks.
"""

from __future__ import annotations

import ctypes
import json
import math
import os
import queue
import random
import sys
import time
import traceback
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / "vendor"))
sys.path.insert(0, str(BASE))

from PIL import Image, ImageChops  # noqa: E402

import settings as pet_settings  # noqa: E402
import sprite  # noqa: E402
import win32 as w32  # noqa: E402

CLASS_NAME = f"BubbleCatPetClass_{os.getpid()}"
TIMER_ID = 1
WM_FEED_CLICK = w32.WM_APP + 1
HOTKEY_ID = 1          # Ctrl+Alt+F : drop a snack at the cursor
HOTKEY_SETTINGS = 2    # Ctrl+Alt+S : open the settings window
HOTKEY_DANCE = 3       # Ctrl+Alt+D : make the pet dance
LOG_PATH = BASE / "pet.log"
STATE_PATH = BASE / "state.json"
SCALE = 1.0  # set at startup from the system DPI


def premultiplied_bgra(image: Image.Image) -> bytes:
    """Pillow RGBA -> premultiplied BGRA bytes for UpdateLayeredWindow."""
    r, g, b, a = image.split()
    premul = Image.merge("RGBA", (
        ImageChops.multiply(r, a),
        ImageChops.multiply(g, a),
        ImageChops.multiply(b, a),
        a,
    ))
    return premul.tobytes("raw", "BGRA")


class PetApp:
    def __init__(self) -> None:
        global SCALE
        SCALE = w32.enable_dpi_awareness()
        self.state = self._load_state()
        self.settings = pet_settings.Settings.from_dict(
            self.state.get("settings") if isinstance(self.state, dict) else None)
        self.scale = SCALE * self.settings.pet_scale
        self.W = int(round(sprite.LOGICAL_W * self.scale))
        self.H = int(round(sprite.LOGICAL_H * self.scale))

        self.vx, self.vy, self.vw, self.vh = w32.virtual_screen()
        self.wx, self.wy, self.ww, self.wh = w32.primary_workarea()

        self.start = time.monotonic()
        self.last_tick = self.start
        self.elapsed = 0.0
        self.pose = sprite.Pose()

        # behaviour ---------------------------------------------------------
        self.mode = "idle"
        self.idle_timer = 0.0
        self.walk_target = (0.0, 0.0)
        self.walk_speed = 300.0 * SCALE
        self.walk_phase = 0.0
        self.facing = 1
        self.pending_food = False
        self.food_xy = (0, 0)
        self.eat_timer = 0.0
        self.eat_duration = 1.5
        self.happy_timer = 0.0
        self.sleep_since = 0.0
        self.look = 0.0
        self.look_target = 0.0
        self.next_look = self.start + 2.0
        self.next_blink = self.start + random.uniform(2.0, 4.0)
        self.blink_until = 0.0
        self.next_roam = self.start + 8.0
        self.next_hungry_say = self.start + 30.0
        self._skip_frame = False

        # user settings -----------------------------------------------------
        self.follow_mouse = self.settings.follow_mouse
        self.roam = self.settings.roam
        self.click_feed = self.settings.click_feed
        self.topmost = self.settings.topmost
        self.opacity = self.settings.opacity
        self.hunger = 86.0
        self.mood = 80.0
        self.custom_img = None
        self.settings_win = None
        self._ui = queue.SimpleQueue()

        # little performances ----------------------------------------------
        self.action = ""
        self.action_timer = 0.0
        self.action_duration = 0.0
        self.next_auto_action = self.start + random.uniform(25.0, 50.0)

        # input state -------------------------------------------------------
        self.pressed = False
        self.dragging = False
        self.press_pt = (0, 0)
        self.press_win = (0.0, 0.0)
        self.click_x = 0

        # feeding hook ------------------------------------------------------
        self.hook = None
        self.hook_proc = None
        self.feed_once = False
        self.arm_deadline = 0.0
        self._pending_click = None

        # speech bubble -----------------------------------------------------
        self.bubble_img = None
        self.bubble_until = 0.0

        self.x = float(self.state.get("x", self.wx + self.ww - self.W - 34))
        self.y = float(self.state.get("y", self.wy + self.wh - self.H - 8))
        self._load_custom_image()
        self._clamp_position()
        self._apply_offline_decay()

        self._proc = w32.WNDPROC(self._wndproc)
        self.hinst = w32.register_class(self._proc, CLASS_NAME)

        self.pet_hwnd = w32.create_popup(
            self.hinst, CLASS_NAME, "泡泡猫", int(self.x), int(self.y),
            self.W, self.H,
        )
        self.pet_surface = w32.LayerSurface(self.pet_hwnd, self.W, self.H)

        fw = int(round(56 * SCALE))
        self.food_size = fw
        self.food_hwnd = w32.create_popup(
            self.hinst, CLASS_NAME, "snack", 0, 0, fw, fw, click_through=True,
        )
        self.food_surface = w32.LayerSurface(self.food_hwnd, fw, fw)
        self.food_img = sprite.render_food(SCALE, 3)
        if self.food_img.size != (fw, fw):
            self.food_img = self.food_img.resize((fw, fw), Image.LANCZOS)
        self.food_surface.blit(premultiplied_bgra(self.food_img), -10000, -10000)
        w32.show_window(self.food_hwnd, False)

        w32.show_window(self.pet_hwnd, True)
        if not self.topmost:
            w32.set_topmost(self.pet_hwnd, False)
            w32.set_topmost(self.food_hwnd, False)
        w32.user32.SetTimer(self.pet_hwnd, TIMER_ID, 33, None)
        try:
            w32.user32.RegisterHotKey(
                self.pet_hwnd, HOTKEY_ID, w32.MOD_CONTROL | w32.MOD_ALT, ord("F"))
            w32.user32.RegisterHotKey(
                self.pet_hwnd, HOTKEY_SETTINGS,
                w32.MOD_CONTROL | w32.MOD_ALT, ord("S"))
            w32.user32.RegisterHotKey(
                self.pet_hwnd, HOTKEY_DANCE,
                w32.MOD_CONTROL | w32.MOD_ALT, ord("D"))
        except Exception:
            pass

        self._save_state()
        self.draw()
        if self.click_feed:
            self._install_hook()
        self.say("你好呀～点我投喂零食", 3.0)

    # ------------------------------------------------------------------ log
    @staticmethod
    def _log(text: str) -> None:
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as fh:
                fh.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {text}\n")
        except Exception:
            pass

    def _log_exc(self) -> None:
        self._log(traceback.format_exc())

    # -------------------------------------------------------------- state ---
    def _load_state(self) -> dict:
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_state(self) -> None:
        data = {
            "x": int(self.x),
            "y": int(self.y),
            "follow_mouse": self.follow_mouse,
            "roam": self.roam,
            "click_feed": self.click_feed,
            "hunger": round(self.hunger, 1),
            "mood": round(self.mood, 1),
            "settings": self.settings.to_dict(),
            "saved": time.time(),
        }
        try:
            STATE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        except Exception:
            self._log_exc()

    def _apply_offline_decay(self) -> None:
        self.hunger = min(100.0, max(0.0, float(self.state.get("hunger", self.hunger))))
        self.mood = min(100.0, max(0.0, float(self.state.get("mood", self.mood))))
        saved = float(self.state.get("saved", 0) or 0)
        if saved <= 0:
            return
        hours = min(24.0, max(0.0, (time.time() - saved) / 3600.0))
        self.hunger = max(5.0, self.hunger - 4.0 * hours)
        self.mood = max(5.0, self.mood - 2.0 * hours)

    # ------------------------------------------------------------- settings -
    def _load_custom_image(self) -> None:
        self.custom_img = None
        path = self.settings.custom_image
        if not path:
            return
        try:
            im = Image.open(path).convert("RGBA")
            im.thumbnail((720, 720), Image.LANCZOS)
            if self.settings.auto_cutout:
                im = sprite.cutout_white(im)
            self.custom_img = im
        except Exception:
            self.custom_img = None
            self._log(f"自定义图片打不开：{path}")

    def _settings_snapshot(self) -> dict:
        mode_text = {
            "walk": "散步中", "eat": "吃东西", "happy": "开心",
            "sleep": "睡觉中", "drag": "被拎着", "action": "表演中",
        }.get(self.mode, "发呆")
        return {
            "settings": self.settings.to_dict(),
            "hunger": self.hunger,
            "mood": self.mood,
            "mode_text": mode_text,
        }

    def _on_settings_change(self, data: dict) -> None:
        self._ui.put(("settings", dict(data or {})))

    def _on_settings_action(self, name: str) -> None:
        self._ui.put(("action", name))

    def _on_settings_command(self, name: str) -> None:
        self._ui.put(("command", name))

    def _open_settings(self) -> None:
        if self.settings_win is not None and not self.settings_win.closed:
            self.say("设置窗口已经开着啦～", 1.8)
            return
        try:
            self.settings_win = pet_settings.SettingsWindow(
                snapshot=self._settings_snapshot,
                on_change=self._on_settings_change,
                on_action=self._on_settings_action,
                on_command=self._on_settings_command,
                dpi_scale=SCALE,
            )
            self.settings_win.start()
        except Exception:
            self.settings_win = None
            self._log_exc()
            self.say("设置窗口打不开…看看 pet.log", 2.4)

    def _drain_ui(self) -> None:
        while True:
            try:
                kind, payload = self._ui.get_nowait()
            except queue.Empty:
                return
            try:
                if kind == "settings":
                    self._apply_settings(dict(payload))
                elif kind == "action":
                    self._start_action(str(payload))
                elif kind == "command":
                    self._ui_command(str(payload))
            except Exception:
                self._log_exc()

    def _apply_settings(self, data: dict) -> None:
        if not data:
            return
        if "pet_scale" in data:
            self._apply_scale(float(data.pop("pet_scale")))
        if "opacity" in data:
            self.opacity = max(0.35, min(1.0, float(data.pop("opacity"))))
            self.settings.opacity = self.opacity
        if "speed" in data:
            self.settings.speed = max(0.5, min(1.8, float(data.pop("speed"))))
        if "custom_image" in data or "model" in data:
            model = str(data.get("model", self.settings.model))
            path = str(data.get("custom_image", self.settings.custom_image) or "")
            self.settings.model = model
            self.settings.custom_image = path
            if model == "custom" and not path:
                self.settings.model = "cream_cat"
            self._load_custom_image()
            data.pop("custom_image", None)
            data.pop("model", None)
        if "auto_cutout" in data:
            self.settings.auto_cutout = bool(data.pop("auto_cutout"))
            self._load_custom_image()
        for key in ("roam", "follow_mouse", "auto_actions", "topmost"):
            if key in data:
                setattr(self.settings, key, bool(data.pop(key)))
                if key == "roam":
                    self.roam = self.settings.roam
                    if self.roam:
                        self.next_roam = time.monotonic() + 4.0
                elif key == "follow_mouse":
                    self.follow_mouse = self.settings.follow_mouse
                elif key == "topmost":
                    self.topmost = self.settings.topmost
                    w32.set_topmost(self.pet_hwnd, self.topmost)
                    w32.set_topmost(self.food_hwnd, self.topmost)
        if "click_feed" in data:
            self.settings.click_feed = bool(data.pop("click_feed"))
            self.click_feed = self.settings.click_feed
            if self.click_feed:
                self._install_hook()
            elif not self.feed_once:
                self._uninstall_hook()
        self.draw()
        self._save_state()

    def _ui_command(self, name: str) -> None:
        if name == "home":
            self._hide_food()
            self.pending_food = False
            self._start_walk(*self._home_target(), speed=380 * self.scale)
            self.say("回家啦～", 1.6)
        elif name == "feed":
            fx = self.x + self.W / 2 + self.facing * 78 * self.scale
            fy = self.y + self.H - 46 * self.scale
            self._spawn_food(fx, fy)
        elif name == "quit":
            self.shutdown()
        elif name == "reset":
            self.hunger = 86.0
            self.mood = 80.0
            self.say("状态重置好啦", 1.8)
        self._save_state()

    def _apply_scale(self, value: float) -> None:
        value = max(0.6, min(1.8, value))
        if abs(value - self.settings.pet_scale) < 1e-3:
            return
        foot_x, foot_y = self._foot()
        self.settings.pet_scale = value
        self.scale = SCALE * value
        self.W = int(round(sprite.LOGICAL_W * self.scale))
        self.H = int(round(sprite.LOGICAL_H * self.scale))
        self.x = foot_x - self.W / 2
        self.y = foot_y - (self.H - 38 * self.scale)
        self._clamp_position()
        try:
            self.pet_surface.destroy()
            w32.resize_window(self.pet_hwnd, int(self.x), int(self.y),
                              self.W, self.H)
            self.pet_surface = w32.LayerSurface(self.pet_hwnd, self.W, self.H)
        except Exception:
            self._log_exc()
        try:
            fw = int(round(56 * self.scale))
            self.food_size = fw
            self.food_img = sprite.render_food(self.scale, 3)
            if self.food_img.size != (fw, fw):
                self.food_img = self.food_img.resize((fw, fw), Image.LANCZOS)
            self.food_surface.destroy()
            w32.resize_window(self.food_hwnd, -10000, -10000, fw, fw)
            self.food_surface = w32.LayerSurface(self.food_hwnd, fw, fw)
            self.food_surface.blit(premultiplied_bgra(self.food_img),
                                   -10000, -10000)
            w32.show_window(self.food_hwnd, False)
        except Exception:
            self._log_exc()

    # -------------------------------------------------------------- actions -
    ACTION_SPECS = {
        "dance": (5.0, 10, ("看我跳舞！", "转个圈～", "华尔兹时间！")),
        "spin": (2.2, 6, ("转圈圈～", "眩晕中…", "看我的旋转！")),
        "hop": (1.6, 5, ("蹦蹦跳跳！", "跳高高～", "接住我！")),
        "roll": (2.4, 6, ("打个滚～", "滚来滚去", "地板上好凉快")),
    }

    def _start_action(self, name: str) -> None:
        spec = self.ACTION_SPECS.get(name)
        if spec is None or self.mode in ("eat", "drag"):
            return
        self._wake()
        if self.pending_food:
            self._hide_food()
            self.pending_food = False
        self.mode = "action"
        self.action = name
        self.action_timer = 0.0
        self.action_duration = spec[0]
        self.mood = min(100.0, self.mood + spec[1])
        self.idle_timer = 0.0
        self.say(random.choice(spec[2]), 2.0)
        self._save_state()

    # ------------------------------------------------------------ geometry -
    def _clamp_position(self) -> None:
        self.x = max(self.vx, min(self.vx + self.vw - self.W, self.x))
        self.y = max(self.vy, min(self.vy + self.vh - self.H, self.y))

    def _foot(self) -> tuple[float, float]:
        return self.x + self.W * 0.5, self.y + self.H - 38 * self.scale

    def _home_target(self) -> tuple[float, float]:
        return (self.wx + self.ww - self.W - 34,
                self.wy + self.wh - self.H - 8)

    # --------------------------------------------------------------- speech -
    def say(self, text: str, seconds: float = 2.6) -> None:
        try:
            self.bubble_img = sprite.render_bubble(text, scale=self.scale)
            self.bubble_until = time.monotonic() + seconds
        except Exception:
            self._log_exc()

    # ------------------------------------------------------------ behaviour -
    def _start_walk(self, tx: float, ty: float, speed: float | None = None) -> None:
        self.walk_target = (tx, ty)
        base = speed if speed is not None else 310.0 * self.scale
        self.walk_speed = base * self.settings.speed
        self.mode = "walk"
        self.idle_timer = 0.0
        self.next_roam = 0.0

    def _arrive(self) -> None:
        if self.pending_food:
            self._start_eat()
        else:
            self.mode = "idle"
            self.idle_timer = 0.0
            self.next_roam = time.monotonic() + random.uniform(10.0, 22.0)

    def _start_roam(self) -> None:
        # short, unhurried strolls so the pet never feels frantic
        tx = self.x + random.uniform(-260, 260) * self.scale
        ty = self.y + random.uniform(-120, 120) * self.scale
        tx = max(self.vx, min(self.vx + self.vw - self.W, tx))
        ty = max(self.vy, min(self.vy + self.vh - self.H, ty))
        self._start_walk(tx, ty, speed=150.0 * self.scale)

    def _start_eat(self) -> None:
        self.mode = "eat"
        self.eat_timer = 0.0
        self.eat_duration = 1.6
        self._hide_food()
        self.pending_food = False
        if self.food_xy[0] >= self.x + self.W / 2:
            self.facing = 1
        else:
            self.facing = -1
        self.say(random.choice(["好吃好吃～", "咔嚓咔嚓", "喵呜，谢谢！",
                                "这个零食我最爱了"]), 2.2)

    def _finish_eat(self) -> None:
        self.hunger = min(100.0, self.hunger + 16.0)
        self.mood = min(100.0, self.mood + 7.0)
        self.mode = "happy"
        self.happy_timer = 1.35
        self.say(random.choice(["吃饱啦～", "喵～心满意足", "还想再来一块…"]), 2.2)
        self._save_state()

    def _wake(self) -> None:
        if self.mode == "sleep":
            self.mode = "idle"
            self.idle_timer = 0.0
            self.sleep_since = 0.0
            self.blink_until = 0.0
            self.say("唔…醒啦！", 2.0)

    # -------------------------------------------------------------- feeding -
    def _spawn_food(self, fx: float, fy: float) -> None:
        self._wake()
        fx = max(self.vx + 24 * self.scale,
                 min(self.vx + self.vw - 24 * self.scale, fx))
        fy = max(self.vy + 24 * self.scale,
                 min(self.vy + self.vh - 24 * self.scale, fy))
        self.food_xy = (fx, fy)
        # window position that puts the cat's mouth right in front of the snack
        foot_x, foot_y = self._foot()
        direction = 1 if fx >= foot_x else -1
        tx = fx - self.W / 2 - direction * 44 * self.scale
        ty = fy - (self.H - 38 * self.scale)
        tx = max(self.vx, min(self.vx + self.vw - self.W, tx))
        ty = max(self.vy, min(self.vy + self.vh - self.H, ty))
        self._show_food(fx, fy)
        self._start_walk(tx, ty, speed=330 * self.scale)
        self.pending_food = True
        self.facing = direction
        self.say(random.choice(["零食！", "冲呀～", "哇，是饼干！"]), 1.5)

    def _show_food(self, fx: float, fy: float) -> None:
        half = self.food_size / 2
        w32.move_window(self.food_hwnd, int(fx - half), int(fy - half))
        w32.show_window(self.food_hwnd, True)

    def _hide_food(self) -> None:
        w32.show_window(self.food_hwnd, False)

    # ---------------------------------------------------------------- mouse -
    def _on_press(self, lparam) -> None:
        if self.mode == "sleep":
            self._wake()
        self.pressed = True
        self.dragging = False
        self.press_pt = w32.cursor_pos()
        self.press_win = (self.x, self.y)
        self.click_x = ctypes.c_short(lparam & 0xFFFF).value
        w32.user32.SetCapture(self.pet_hwnd)

    def _on_move(self) -> None:
        if not self.pressed:
            return
        cx, cy = w32.cursor_pos()
        dx = cx - self.press_pt[0]
        dy = cy - self.press_pt[1]
        if not self.dragging and abs(dx) + abs(dy) > 5:
            self.dragging = True
            self.mode = "drag"
            self.pending_food = False
            self._hide_food()
            self.say("放我下来啦～", 1.4)
        if self.dragging:
            self.x = self.press_win[0] + dx
            self.y = self.press_win[1] + dy
            self._clamp_position()

    def _on_release(self) -> None:
        if not self.pressed:
            return
        was_drag = self.dragging
        self.pressed = False
        self.dragging = False
        self.facing = 1 if self.click_x > self.W / 2 else -1
        w32.user32.ReleaseCapture()
        if was_drag:
            self.mode = "idle"
            self._save_state()
            self.say("这里也不错～", 1.8)
            return
        self._on_click()

    def _on_click(self) -> None:
        if self.mode in ("eat", "happy") or self.pending_food:
            self.mode = "happy"
            self.happy_timer = 1.1
            self.mood = min(100.0, self.mood + 4.0)
            self.say(random.choice(["呼噜呼噜…", "再摸摸～", "喵～"]), 1.8)
            return
        fx = self.x + self.W / 2 + self.facing * 78 * self.scale
        fy = self.y + self.H - 46 * self.scale
        self._spawn_food(fx, fy)

    # ------------------------------------------------------------- feeding UI
    def _install_hook(self) -> None:
        if self.hook is not None:
            return
        try:
            self.hook, self.hook_proc = w32.install_mouse_hook(self._on_hook_click)
        except Exception:
            self._log_exc()
            self.hook = None

    def _uninstall_hook(self) -> None:
        if self.hook is not None:
            try:
                w32.uninstall_mouse_hook(self.hook)
            except Exception:
                self._log_exc()
            self.hook = None
            self.hook_proc = None

    def _on_hook_click(self, x: int, y: int) -> None:
        if w32.is_our_window_at(x, y):
            return
        if self.pet_hwnd:
            self._pending_click = (x, y)
            w32.user32.PostMessageW(self.pet_hwnd, WM_FEED_CLICK, 0, 0)

    def _on_global_click(self) -> None:
        if self._pending_click is None:
            return
        x, y = self._pending_click
        self._pending_click = None
        if self.feed_once:
            self.feed_once = False
            self.arm_deadline = 0.0
            if not self.click_feed:
                self._uninstall_hook()
        self._spawn_food(x, y)

    def _arm_one_shot(self) -> None:
        if self.click_feed:
            self._spawn_food(*w32.cursor_pos())
            return
        self.feed_once = True
        self.arm_deadline = time.monotonic() + 20.0
        self._install_hook()
        self.say("点桌面任意位置，我就过去～", 3.0)

    def _cancel_arm(self) -> None:
        self.feed_once = False
        self.arm_deadline = 0.0
        if not self.click_feed:
            self._uninstall_hook()

    # ---------------------------------------------------------------- menu --
    def _show_menu(self) -> None:
        mx, my = w32.cursor_pos()
        checked = w32.MF_CHECKED if self.follow_mouse else w32.MF_UNCHECKED
        roam = w32.MF_CHECKED if self.roam else w32.MF_UNCHECKED
        feed = w32.MF_CHECKED if self.click_feed else w32.MF_UNCHECKED
        if self.feed_once:
            feed_label = "取消投喂定位"
            feed_cmd = 12
        else:
            feed_label = "投喂零食…（点桌面定位）"
            feed_cmd = 1
        items = [
            (13, "设置与自定义…", 0),
            (14, "跳个舞", 0),
            None,
            (feed_cmd, feed_label, 0),
            (2, "摸摸头", 0),
            (3, "陪它玩一下", 0),
            (4, "叫醒它" if self.mode == "sleep" else "去睡觉", 0),
            None,
            (5, "跟随鼠标", checked),
            (6, "自由漫游", roam),
            (7, "单击桌面就投喂", feed),
            None,
            (8, f"饱食度 {int(self.hunger)}%　心情 {int(self.mood)}%",
             w32.MF_GRAYED),
            None,
            (9, "回到屏幕右下角", 0),
            (10, "重置状态", 0),
            (11, "退出", 0),
        ]
        cmd = w32.popup_menu(self.pet_hwnd, items, mx, my)
        if not cmd:
            return
        if cmd == 1:
            self._arm_one_shot()
        elif cmd == 13:
            self._open_settings()
        elif cmd == 14:
            self._start_action("dance")
        elif cmd == 12:
            self._cancel_arm()
            self.say("好，不喂啦～", 1.6)
        elif cmd == 2:
            self._wake()
            self.mode = "happy"
            self.happy_timer = 1.3
            self.mood = min(100.0, self.mood + 5.0)
            self.say("呼噜呼噜…好舒服", 2.2)
        elif cmd == 3:
            self._wake()
            self.mode = "happy"
            self.happy_timer = 1.8
            self.mood = min(100.0, self.mood + 8.0)
            self.say("一起玩～接住！", 2.2)
        elif cmd == 4:
            if self.mode == "sleep":
                self._wake()
            else:
                self._hide_food()
                self.pending_food = False
                self.mode = "sleep"
                self.sleep_since = time.monotonic()
                self.say("晚安…zzZ", 2.0)
        elif cmd == 5:
            self.follow_mouse = not self.follow_mouse
            self.say("跟着你走～" if self.follow_mouse else "我在这儿等你",
                     1.8)
        elif cmd == 6:
            self.roam = not self.roam
            self.say("自己溜达去～" if self.roam else "不乱跑啦", 1.8)
        elif cmd == 7:
            self.click_feed = not self.click_feed
            if self.click_feed:
                self._install_hook()
                self.say("点桌面任意地方都会掉零食！", 2.6)
            else:
                if not self.feed_once:
                    self._uninstall_hook()
                self.say("不自动投喂啦", 1.8)
        elif cmd == 8:
            pass
        elif cmd == 9:
            self._hide_food()
            self.pending_food = False
            self._start_walk(*self._home_target(), speed=380 * self.scale)
            self.say("回家啦～", 1.6)
        elif cmd == 10:
            self.hunger = 86.0
            self.mood = 80.0
            self.say("状态重置好啦", 1.8)
        elif cmd == 11:
            self.shutdown()
            return
        self._save_state()

    # ------------------------------------------------------------------ tick
    def _tick(self) -> None:
        now = time.monotonic()
        dt = max(0.0, min(0.1, now - self.last_tick))
        self.last_tick = now
        self.elapsed += dt
        self.pose.t = self.elapsed
        self._drain_ui()
        if self.bubble_img is not None and now >= self.bubble_until:
            self.bubble_img = None

        self.hunger = max(0.0, self.hunger - 0.012 * dt)
        self.mood = max(0.0, self.mood - 0.004 * dt)

        if now > self.next_blink and self.mode != "sleep":
            self.blink_until = now + 0.13
            self.next_blink = now + random.uniform(2.4, 6.5)
        self.pose.blink = 1.0 if now < self.blink_until else 0.0

        if now > self.next_look:
            self.look_target = random.uniform(-1.0, 1.0)
            self.next_look = now + random.uniform(1.8, 4.5)
        self.look += (self.look_target - self.look) * min(1.0, dt * 5.0)

        if self.feed_once and now > self.arm_deadline:
            self._cancel_arm()
            self.say("不等啦，先收起来～", 2.0)

        if self.mode == "walk":
            self._step_walk(dt, now)
        elif self.mode == "eat":
            self.eat_timer += dt
            if self.eat_timer >= self.eat_duration:
                self._finish_eat()
        elif self.mode == "happy":
            self.happy_timer -= dt
            if self.happy_timer <= 0:
                self.mode = "idle"
                self.idle_timer = 0.0
                self.next_roam = now + random.uniform(10.0, 22.0)
        elif self.mode == "action":
            self.action_timer += dt
            if self.action_timer >= self.action_duration:
                self.mode = "happy"
                self.happy_timer = 0.7
                self.action = ""
                self.next_roam = now + random.uniform(10.0, 22.0)
        elif self.mode == "sleep":
            self.idle_timer += dt
            if now - self.sleep_since > 1500:
                self._wake()
        elif self.mode == "idle":
            self.idle_timer += dt
            if self.idle_timer > 300:
                self.mode = "sleep"
                self.sleep_since = now
                self.say("困了…先睡一觉", 2.2)
            elif (self.settings.auto_actions and self.idle_timer > 6.0
                  and now > self.next_auto_action):
                self.next_auto_action = now + random.uniform(28.0, 70.0)
                self._start_action(random.choice(("dance", "spin", "hop", "roll")))
            elif self.follow_mouse:
                self._follow_cursor(now, dt)
            elif self.roam and now > self.next_roam:
                self._start_roam()
            if self.mode == "idle" and self.hunger < 25 and now > self.next_hungry_say:
                self.say("肚子饿啦…点我投喂嘛", 2.6)
                self.next_hungry_say = now + 90.0

        # when the cat is just sitting there, half the frame rate is
        # indistinguishable and saves a chunk of CPU
        self._skip_frame = not self._skip_frame
        settled = self.mode in ("idle", "sleep") and self.bubble_img is None
        if settled and not self.pressed and self._skip_frame:
            return

        self.draw(now)

    def _step_walk(self, dt: float, now: float) -> None:
        if self.follow_mouse and not self.pending_food:
            cx, cy = w32.cursor_pos()
            tx = cx - self.W / 2
            ty = cy - self.H * 0.52
            tx = max(self.vx, min(self.vx + self.vw - self.W, tx))
            ty = max(self.vy, min(self.vy + self.vh - self.H, ty))
            if math.hypot(tx - self.x, ty - self.y) > 80 * self.scale:
                self.walk_target = (tx, ty)
        tx, ty = self.walk_target
        dx, dy = tx - self.x, ty - self.y
        dist = math.hypot(dx, dy)
        if abs(dx) > 0.5:
            self.facing = 1 if dx > 0 else -1
        if self.pending_food:
            fx, fy = self.food_xy
            fdx = fx - (self.x + self.W / 2)
            fdy = fy - (self.y + self.H - 38 * self.scale)
            if math.hypot(fdx, fdy) <= 64 * self.scale:
                self._start_eat()
                return
        if dist <= 1.5:
            self._arrive()
            return
        step = min(dist, self.walk_speed * dt)
        self.x += dx / dist * step
        self.y += dy / dist * step
        self.walk_phase += dt * 2.4
        if dist <= 3:
            self._arrive()

    def _follow_cursor(self, now: float, dt: float) -> None:
        cx, cy = w32.cursor_pos()
        tx = cx - self.W / 2
        ty = cy - self.H * 0.52
        tx = max(self.vx, min(self.vx + self.vw - self.W, tx))
        ty = max(self.vy, min(self.vy + self.vh - self.H, ty))
        dist = math.hypot(tx - self.x, ty - self.y)
        if dist > 140 * self.scale:
            self._start_walk(tx, ty, speed=420.0 * self.scale)
        elif dist < 90 * self.scale:
            self.next_roam = now + 3.0

    # ------------------------------------------------------------------ draw
    def draw(self, now: float | None = None) -> None:
        if now is None:
            now = time.monotonic()
        pose = self.pose
        pose.state = self.mode
        pose.facing = self.facing
        pose.walk_phase = self.walk_phase
        pose.look = self.look if self.mode in ("idle", "walk") else 0.0
        pose.happy = 1.0 if self.mode == "happy" else 0.0
        pose.eat_frac = 0.0
        pose.action = ""
        pose.hop = 0.0
        pose.squash = 1.0
        pose.spin = 0.0
        pose.tail_wag = 0.0
        pose.notes = 0.0
        if self.mode == "action":
            pose.state = "action"
            pose.action = self.action
            self._action_pose(pose)
        if self.mode == "eat":
            pose.mouth = 0.35 + 0.65 * abs(math.sin(self.eat_timer * 11.0))
            pose.eat_frac = max(0.0, 1.0 - self.eat_timer / self.eat_duration)
        elif self.mode == "drag":
            pose.mouth = 0.45
        else:
            pose.mouth = 0.0
        if self.mode == "sleep":
            pose.blink = 0.0

        try:
            skin = sprite.SKINS.get(self.settings.model)
            if self.settings.model == "custom" and self.custom_img is not None:
                img = sprite.render_custom(pose, self.custom_img, self.scale)
            else:
                img = sprite.render_cat(pose, scale=self.scale, ss=2, skin=skin)
            if self.bubble_img is not None and now < self.bubble_until:
                bubble = self.bubble_img
                remain = self.bubble_until - now
                if remain < 0.45:
                    bubble = bubble.copy()
                    bubble.putalpha(bubble.getchannel("A").point(
                        lambda v: int(v * max(0.0, remain / 0.45))))
                bx = (self.W - bubble.width) // 2
                by = max(0, int(88 * self.scale) - bubble.height)
                img.alpha_composite(bubble, (bx, by))
            if self.opacity < 0.999:
                img.putalpha(img.getchannel("A").point(
                    lambda v: int(v * self.opacity)))
            self.pet_surface.blit(premultiplied_bgra(img), int(self.x), int(self.y))
        except Exception:
            self._log_exc()

    def _action_pose(self, pose: "sprite.Pose") -> None:
        """Turn the action timeline into the pose fields sprite.py understands."""
        d = max(0.01, self.action_duration)
        p = min(1.0, self.action_timer / d)
        t = self.action_timer
        if self.action == "dance":
            pose.spin = 300.0 * p
            pose.hop = abs(math.sin(t * math.pi * 2.5)) * 10.0
            pose.tail_wag = math.sin(t * 11.0) * 0.65
            pose.notes = 1.0
            pose.squash = 1.0 - 0.03 * abs(math.sin(t * math.pi * 2.5))
        elif self.action == "spin":
            pose.spin = 720.0 * p
            pose.hop = abs(math.sin(t * math.pi * 4.0)) * 6.0
            pose.tail_wag = math.sin(t * 14.0) * 0.4
        elif self.action == "hop":
            pose.hop = abs(math.sin(t * math.pi * 4.0)) * 24.0
            pose.squash = 1.0 - 0.07 * max(0.0, math.cos(t * math.pi * 4.0))
            pose.tail_wag = math.sin(t * 10.0) * 0.5
        elif self.action == "roll":
            pose.spin = 360.0 * p
            pose.hop = abs(math.sin(t * math.pi * 2.0)) * 5.0
            pose.squash = 1.0 - 0.10 * abs(math.sin(t * math.pi * 2.0))
            pose.tail_wag = math.sin(t * 12.0) * 0.6
            pose.notes = 0.35

    # ------------------------------------------------------------- messages -
    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if hwnd == getattr(self, "food_hwnd", None):
                if msg == w32.WM_NCHITTEST:
                    return w32.HTTRANSPARENT
                if msg == w32.WM_DESTROY:
                    return 0
            elif hwnd == getattr(self, "pet_hwnd", None):
                if msg == w32.WM_TIMER:
                    self._tick()
                    return 0
                if msg == w32.WM_LBUTTONDOWN:
                    self._on_press(lparam)
                    return 0
                if msg == w32.WM_MOUSEMOVE:
                    self._on_move()
                    return 0
                if msg == w32.WM_LBUTTONUP:
                    self._on_release()
                    return 0
                if msg == w32.WM_CAPTURECHANGED:
                    self.pressed = False
                    self.dragging = False
                    return 0
                if msg == w32.WM_RBUTTONUP:
                    self._show_menu()
                    return 0
                if msg == w32.WM_HOTKEY and wparam == HOTKEY_ID:
                    self._spawn_food(*w32.cursor_pos())
                    return 0
                if msg == w32.WM_HOTKEY and wparam == HOTKEY_SETTINGS:
                    self._open_settings()
                    return 0
                if msg == w32.WM_HOTKEY and wparam == HOTKEY_DANCE:
                    self._start_action("dance")
                    return 0
                if msg == WM_FEED_CLICK:
                    self._on_global_click()
                    return 0
                if msg == w32.WM_ERASEBKGND:
                    return 1
                if msg == w32.WM_CLOSE:
                    self.shutdown()
                    return 0
                if msg == w32.WM_DESTROY:
                    w32.user32.PostQuitMessage(0)
                    return 0
        except Exception:
            self._log_exc()
        return w32.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    # --------------------------------------------------------------- teardown
    def shutdown(self) -> None:
        if getattr(self, "_dead", False):
            return
        self._dead = True
        self._save_state()
        self._uninstall_hook()
        try:
            w32.user32.KillTimer(self.pet_hwnd, TIMER_ID)
            for hid in (HOTKEY_ID, HOTKEY_SETTINGS, HOTKEY_DANCE):
                w32.user32.UnregisterHotKey(self.pet_hwnd, hid)
        except Exception:
            pass
        try:
            self._hide_food()
            w32.user32.DestroyWindow(self.food_hwnd)
            w32.user32.DestroyWindow(self.pet_hwnd)
        except Exception:
            self._log_exc()
        try:
            self.food_surface.destroy()
            self.pet_surface.destroy()
        except Exception:
            pass


def main() -> None:
    if not w32.single_instance("BubbleCatPet_SingleInstance"):
        w32.user32.MessageBoxW(None, "泡泡猫已经在桌面上了～", "泡泡猫", 0x40)
        return
    try:
        app = PetApp()
    except Exception:
        text = traceback.format_exc()
        try:
            LOG_PATH.write_text(text, encoding="utf-8")
        except Exception:
            pass
        w32.user32.MessageBoxW(None, text[-1500:], "泡泡猫启动失败", 0x10)
        return
    globals()["APP"] = app
    w32.message_loop()


if __name__ == "__main__":
    main()
