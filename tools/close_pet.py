"""Gracefully close a running Bubble Cat (sends WM_CLOSE to its window)."""
import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
target = []


def cb(hwnd, lparam):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    if buf.value.startswith("BubbleCatPetClass_"):
        target.append(hwnd)
    return True


cbp = WNDENUMPROC(cb)
user32.EnumWindows(cbp, 0)
if not target:
    print("no pet running")
else:
    for hwnd in target:
        user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
    print(f"asked {len(target)} window(s) to close")
