"""Thin ctypes layer for the Windows APIs the desktop pet needs.

Kept deliberately small: one per-pixel-alpha layered popup window, a timer,
a native popup menu and the low-level mouse hook used for click-to-feed.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes as wt

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
try:
    shcore = ctypes.WinDLL("shcore", use_last_error=True)
except OSError:  # pragma: no cover - older Windows
    shcore = None

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wt.WPARAM, wt.LPARAM)

# window styles --------------------------------------------------------------
WS_POPUP = 0x80000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
CS_DBLCLKS = 0x0008
CS_HREDRAW = 0x0002
CS_VREDRAW = 0x0001
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
IDC_ARROW = 32512

# messages -------------------------------------------------------------------
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_PAINT = 0x000F
WM_ERASEBKGND = 0x0014
WM_NCHITTEST = 0x0084
WM_TIMER = 0x0113
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_CAPTURECHANGED = 0x0215
WM_HOTKEY = 0x0312
WM_APP = 0x8000
WM_NULL = 0x0000
HTTRANSPARENT = -1

# menu -----------------------------------------------------------------------
MF_STRING = 0x0000
MF_SEPARATOR = 0x0800
MF_GRAYED = 0x0001
MF_CHECKED = 0x0008
MF_UNCHECKED = 0x0000
TPM_RETURNCMD = 0x0100
TPM_RIGHTBUTTON = 0x0002
TPM_TOPALIGN = 0x0000
TPM_LEFTALIGN = 0x0000

# misc -----------------------------------------------------------------------
SPI_GETWORKAREA = 0x0030
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
WH_MOUSE_LL = 14
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
DIB_RGB_COLORS = 0
ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wt.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HINSTANCE),
        ("hIcon", wt.HICON),
        ("hCursor", wt.HANDLE),
        ("hbrBackground", wt.HBRUSH),
        ("lpszMenuName", wt.LPCWSTR),
        ("lpszClassName", wt.LPCWSTR),
    ]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_ubyte),
        ("BlendFlags", ctypes.c_ubyte),
        ("SourceConstantAlpha", ctypes.c_ubyte),
        ("AlphaFormat", ctypes.c_ubyte),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD),
        ("biWidth", wt.LONG),
        ("biHeight", wt.LONG),
        ("biPlanes", wt.WORD),
        ("biBitCount", wt.WORD),
        ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD),
        ("biXPelsPerMeter", wt.LONG),
        ("biYPelsPerMeter", wt.LONG),
        ("biClrUsed", wt.DWORD),
        ("biClrImportant", wt.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", wt.DWORD * 3),
    ]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wt.POINT),
        ("mouseData", wt.DWORD),
        ("flags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


# prototypes -----------------------------------------------------------------
user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.RegisterClassW.restype = wt.ATOM
user32.CreateWindowExW.argtypes = [
    wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID,
]
user32.CreateWindowExW.restype = wt.HWND
user32.DestroyWindow.argtypes = [wt.HWND]
user32.DestroyWindow.restype = wt.BOOL
user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
user32.ShowWindow.restype = wt.BOOL
user32.SetWindowPos.argtypes = [
    wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, wt.UINT,
]
user32.SetWindowPos.restype = wt.BOOL
user32.UpdateLayeredWindow.argtypes = [
    wt.HWND, wt.HDC, ctypes.POINTER(wt.POINT), ctypes.POINTER(wt.SIZE),
    wt.HDC, ctypes.POINTER(wt.POINT), wt.DWORD,
    ctypes.POINTER(BLENDFUNCTION), wt.DWORD,
]
user32.UpdateLayeredWindow.restype = wt.BOOL
user32.GetDC.argtypes = [wt.HWND]
user32.GetDC.restype = wt.HDC
user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
user32.GetMessageW.restype = ctypes.c_int
user32.PeekMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT, wt.UINT]
user32.PeekMessageW.restype = wt.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.PostMessageW.restype = wt.BOOL
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.SetTimer.argtypes = [wt.HWND, ctypes.c_size_t, wt.UINT, wt.LPVOID]
user32.SetTimer.restype = ctypes.c_size_t
user32.KillTimer.argtypes = [wt.HWND, ctypes.c_size_t]
user32.KillTimer.restype = wt.BOOL
user32.SetCapture.argtypes = [wt.HWND]
user32.SetCapture.restype = wt.HWND
user32.ReleaseCapture.argtypes = []
user32.ReleaseCapture.restype = wt.BOOL
user32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
user32.GetCursorPos.restype = wt.BOOL
user32.WindowFromPoint.argtypes = [wt.POINT]
user32.WindowFromPoint.restype = wt.HWND
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowThreadProcessId.restype = wt.DWORD
user32.SetForegroundWindow.argtypes = [wt.HWND]
user32.SetForegroundWindow.restype = wt.BOOL
user32.LoadCursorW.argtypes = [wt.HINSTANCE, wt.LPCWSTR]
user32.LoadCursorW.restype = wt.HANDLE
user32.CreatePopupMenu.restype = wt.HMENU
user32.AppendMenuW.argtypes = [wt.HMENU, wt.UINT, ctypes.c_size_t, wt.LPCWSTR]
user32.AppendMenuW.restype = wt.BOOL
user32.TrackPopupMenu.argtypes = [
    wt.HMENU, wt.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wt.HWND, ctypes.c_void_p,
]
user32.TrackPopupMenu.restype = ctypes.c_int
user32.DestroyMenu.argtypes = [wt.HMENU]
user32.DestroyMenu.restype = wt.BOOL
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wt.HINSTANCE, wt.DWORD]
user32.SetWindowsHookExW.restype = wt.HANDLE
user32.CallNextHookEx.argtypes = [wt.HANDLE, ctypes.c_int, wt.WPARAM, wt.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [wt.HANDLE]
user32.UnhookWindowsHookEx.restype = wt.BOOL
user32.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT]
user32.RegisterHotKey.restype = wt.BOOL
user32.UnregisterHotKey.argtypes = [wt.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wt.BOOL
user32.SystemParametersInfoW.argtypes = [wt.UINT, wt.UINT, ctypes.c_void_p, wt.UINT]
user32.SystemParametersInfoW.restype = wt.BOOL
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.GetDpiForSystem.restype = wt.UINT
user32.MessageBoxW.argtypes = [wt.HWND, wt.LPCWSTR, wt.LPCWSTR, wt.UINT]
user32.MessageBoxW.restype = ctypes.c_int

gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
gdi32.CreateCompatibleDC.restype = wt.HDC
gdi32.CreateDIBSection.argtypes = [
    wt.HDC, ctypes.POINTER(BITMAPINFO), wt.UINT,
    ctypes.POINTER(ctypes.c_void_p), wt.HANDLE, wt.DWORD,
]
gdi32.CreateDIBSection.restype = wt.HBITMAP
gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
gdi32.SelectObject.restype = wt.HGDIOBJ
gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
gdi32.DeleteObject.restype = wt.BOOL
gdi32.DeleteDC.argtypes = [wt.HDC]
gdi32.DeleteDC.restype = wt.BOOL

kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
kernel32.GetModuleHandleW.restype = wt.HINSTANCE
kernel32.CreateMutexW.argtypes = [wt.LPVOID, wt.BOOL, wt.LPCWSTR]
kernel32.CreateMutexW.restype = wt.HANDLE
kernel32.GetLastError.restype = wt.DWORD
kernel32.SetLastError.argtypes = [wt.DWORD]


def enable_dpi_awareness() -> float:
    """Make the process per-monitor DPI aware and return its initial scale."""
    try:
        shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass
    try:
        dpi = user32.GetDpiForSystem()
    except Exception:
        dpi = 96
    return max(1.0, min(2.0, dpi / 96.0))


def primary_workarea() -> tuple[int, int, int, int]:
    rect = wt.RECT()
    user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top


def virtual_screen() -> tuple[int, int, int, int]:
    return (
        user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_CXVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_CYVIRTUALSCREEN),
    )


def cursor_pos() -> tuple[int, int]:
    pt = wt.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def is_our_window_at(x: int, y: int) -> bool:
    hwnd = user32.WindowFromPoint(wt.POINT(x, y))
    if not hwnd:
        return False
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value == os.getpid()


def register_class(proc: WNDPROC, class_name: str) -> wt.HINSTANCE:
    hinst = kernel32.GetModuleHandleW(None)
    wc = WNDCLASSW()
    wc.style = CS_DBLCLKS | CS_HREDRAW | CS_VREDRAW
    wc.lpfnWndProc = proc
    wc.hInstance = hinst
    wc.hCursor = user32.LoadCursorW(None, wt.LPCWSTR(IDC_ARROW))
    wc.lpszClassName = class_name
    atom = user32.RegisterClassW(ctypes.byref(wc))
    if not atom:
        err = ctypes.get_last_error()
        # 1410 = class already registered (a previous pet instance in-process)
        if err not in (0, 1410):
            raise ctypes.WinError(err)
    return hinst


def create_popup(hinst, class_name: str, title: str, x: int, y: int,
                 width: int, height: int, click_through: bool = False) -> wt.HWND:
    ex = WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_TOPMOST
    if click_through:
        ex |= WS_EX_NOACTIVATE
    hwnd = user32.CreateWindowExW(
        ex, class_name, title, WS_POPUP,
        x, y, width, height, None, None, hinst, None,
    )
    if not hwnd:
        raise ctypes.WinError(ctypes.get_last_error())
    return hwnd


class LayerSurface:
    """A 32-bit top-down DIB kept in sync with a layered window."""

    def __init__(self, hwnd: wt.HWND, width: int, height: int):
        self.hwnd = hwnd
        self.width = width
        self.height = height
        self.screen_dc = user32.GetDC(None)
        self.mem_dc = gdi32.CreateCompatibleDC(self.screen_dc)
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0  # BI_RGB
        self.bits = ctypes.c_void_p()
        self.bitmap = gdi32.CreateDIBSection(
            self.screen_dc, ctypes.byref(bmi), DIB_RGB_COLORS,
            ctypes.byref(self.bits), None, 0,
        )
        if not self.bitmap:
            raise ctypes.WinError(ctypes.get_last_error())
        gdi32.SelectObject(self.mem_dc, self.bitmap)

    def blit(self, bgra: bytes, x: int, y: int) -> None:
        size = self.width * self.height * 4
        if len(bgra) != size:
            raise ValueError(f"expected {size} bytes, got {len(bgra)}")
        ctypes.memmove(self.bits, bgra, size)
        pt_dst = wt.POINT(x, y)
        size_obj = wt.SIZE(self.width, self.height)
        pt_src = wt.POINT(0, 0)
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        ok = user32.UpdateLayeredWindow(
            self.hwnd, self.screen_dc, ctypes.byref(pt_dst),
            ctypes.byref(size_obj), self.mem_dc, ctypes.byref(pt_src),
            0, ctypes.byref(blend), ULW_ALPHA,
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())

    def destroy(self) -> None:
        try:
            gdi32.DeleteObject(self.bitmap)
            gdi32.DeleteDC(self.mem_dc)
            user32.ReleaseDC(None, self.screen_dc)
        except Exception:
            pass
        self.bitmap = None
        self.mem_dc = None
        self.screen_dc = None


def show_window(hwnd, show: bool = True) -> None:
    user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE if show else SW_HIDE)


def move_window(hwnd, x: int, y: int) -> None:
    user32.SetWindowPos(hwnd, None, x, y, 0, 0,
                        SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)


def resize_window(hwnd, x: int, y: int, w: int, h: int) -> None:
    user32.SetWindowPos(hwnd, None, x, y, w, h,
                        SWP_NOZORDER | SWP_NOACTIVATE)


def set_topmost(hwnd, on: bool) -> None:
    user32.SetWindowPos(hwnd, HWND_TOPMOST if on else HWND_NOTOPMOST,
                        0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


def popup_menu(hwnd, items: list[tuple[int, str, int] | None],
               x: int, y: int) -> int:
    menu = user32.CreatePopupMenu()
    for item in items:
        if item is None:
            user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        else:
            cmd, label, flags = item
            user32.AppendMenuW(menu, MF_STRING | flags, cmd, label)
    user32.SetForegroundWindow(hwnd)
    cmd = user32.TrackPopupMenu(
        menu, TPM_RETURNCMD | TPM_RIGHTBUTTON | TPM_TOPALIGN | TPM_LEFTALIGN,
        x, y, 0, hwnd, None,
    )
    user32.PostMessageW(hwnd, WM_NULL, 0, 0)
    user32.DestroyMenu(menu)
    return cmd


def install_mouse_hook(callback):
    """Install a WH_MOUSE_LL hook; returns (handle, ref)."""
    @HOOKPROC
    def _proc(n_code, w_param, l_param):
        if n_code == 0 and w_param == WM_LBUTTONDOWN:
            info = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            try:
                callback(info.pt.x, info.pt.y)
            except Exception:
                pass
        return user32.CallNextHookEx(None, n_code, w_param, l_param)

    hook = user32.SetWindowsHookExW(WH_MOUSE_LL, _proc, None, 0)
    if not hook:
        raise ctypes.WinError(ctypes.get_last_error())
    return hook, _proc


def uninstall_mouse_hook(hook) -> None:
    if hook:
        user32.UnhookWindowsHookEx(hook)


def message_loop() -> None:
    msg = wt.MSG()
    while True:
        ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
        if ret in (0, -1):
            break
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


def single_instance(name: str) -> bool:
    kernel32.CreateMutexW(None, False, name)
    return kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS
