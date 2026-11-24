"""按 HWND 获取客户区图像，不激活窗口，也不截取覆盖在窗口上的其他程序。"""

import ctypes
from ctypes import wintypes

import numpy as np
import win32gui


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _BitmapInfo(ctypes.Structure):
    _fields_ = [("bmiHeader", _BitmapInfoHeader), ("bmiColors", wintypes.DWORD * 1)]


class BackgroundWindowCapture:
    def __init__(self, hwnd):
        self.hwnd = hwnd
        self._print_window = ctypes.windll.user32.PrintWindow
        self._print_window.argtypes = (wintypes.HWND, wintypes.HDC, wintypes.UINT)
        self._print_window.restype = wintypes.BOOL
        # 直接使用系统 GDI，避免引入 win32ui 及其额外的 MFC 运行库依赖。
        gdi = ctypes.WinDLL("gdi32", use_last_error=True)
        bindings = (
            ("_create_dc", "CreateCompatibleDC", (wintypes.HDC,), wintypes.HDC),
            ("_create_bitmap", "CreateDIBSection", (
                wintypes.HDC, ctypes.POINTER(_BitmapInfo), wintypes.UINT,
                ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD,
            ), wintypes.HANDLE),
            ("_select_object", "SelectObject", (wintypes.HDC, wintypes.HANDLE), wintypes.HANDLE),
            ("_delete_object", "DeleteObject", (wintypes.HANDLE,), wintypes.BOOL),
            ("_delete_dc", "DeleteDC", (wintypes.HDC,), wintypes.BOOL),
            ("_flush", "GdiFlush", (), wintypes.BOOL),
        )
        for attribute, name, arguments, result in bindings:
            function = getattr(gdi, name)
            function.argtypes = arguments
            function.restype = result
            setattr(self, attribute, function)

    def capture(self):
        if not win32gui.IsWindow(self.hwnd):
            raise RuntimeError("游戏窗口已失效")
        if win32gui.IsIconic(self.hwnd):
            raise RuntimeError("游戏窗口已最小化，等待窗口恢复渲染")
        left, top, right, bottom = win32gui.GetClientRect(self.hwnd)
        width, height = right - left, bottom - top
        if width <= 0 or height <= 0:
            raise RuntimeError("游戏窗口客户区不可用")
        handle = win32gui.GetDC(self.hwnd)
        if not handle:
            raise RuntimeError("无法获取游戏窗口绘图上下文")
        memory_dc = bitmap = previous = None
        try:
            memory_dc = self._create_dc(handle)
            if not memory_dc:
                raise RuntimeError("无法创建游戏截图绘图上下文")
            info = _BitmapInfo()
            info.bmiHeader.biSize = ctypes.sizeof(_BitmapInfoHeader)
            info.bmiHeader.biWidth = width
            info.bmiHeader.biHeight = -height  # 顶部起始，直接得到 BGR 图像方向。
            info.bmiHeader.biPlanes = 1
            info.bmiHeader.biBitCount = 32
            info.bmiHeader.biCompression = 0  # BI_RGB
            bits = ctypes.c_void_p()
            bitmap = self._create_bitmap(handle, ctypes.byref(info), 0,
                                         ctypes.byref(bits), None, 0)
            if not bitmap or not bits.value:
                raise RuntimeError("无法创建游戏截图位图")
            previous = self._select_object(memory_dc, bitmap)
            if not previous or previous == ctypes.c_void_p(-1).value:
                previous = None
                raise RuntimeError("无法选择游戏截图位图")
            # PW_CLIENTONLY | PW_RENDERFULLCONTENT；在识别线程中调用，避免阻塞界面。
            if not self._print_window(self.hwnd, memory_dc, 0x00000003):
                raise RuntimeError("后台窗口截图失败")
            self._flush()
            pixels = np.ctypeslib.as_array(
                (ctypes.c_uint8 * (width * height * 4)).from_address(bits.value))
            frame = pixels.reshape(height, width, 4)[:, :, :3].copy()
            sample = frame[::max(1, height // 100), ::max(1, width // 100)]
            if int(sample.max()) < 16:
                raise RuntimeError("后台窗口未返回有效画面，等待游戏恢复渲染")
            return frame
        finally:
            # 即使窗口在截图途中关闭，也逐个释放 GDI 对象，不掩盖截图错误。
            cleanups = []
            if memory_dc is not None and previous is not None:
                cleanups.append(lambda: self._select_object(memory_dc, previous))
            if bitmap:
                cleanups.append(lambda: self._delete_object(bitmap))
            if memory_dc:
                cleanups.append(lambda: self._delete_dc(memory_dc))
            cleanups.append(lambda: win32gui.ReleaseDC(self.hwnd, handle))
            for cleanup in cleanups:
                try:
                    cleanup()
                except Exception:
                    pass
