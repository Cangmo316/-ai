"""用 ctypes 调 PrintWindow 抓窗口，导出 PIL 图像。

为什么不用 PowerShell + Add-Type：
  1) 这台机器 150% DPI，PowerShell 里拿到的窗口矩形是逻辑像素，截图会偏移；
  2) UE 视口是 D3D 渲染，CopyFromScreen 常拿到黑块，必须 PrintWindow(flag=2)；
  3) C# 的 Bitmap 重载在 PowerShell 里调不稳（Clone 两参数、Bitmap(src,w,h) 都踩过）。
Python 里用 ctypes 直接走 GDI，配合 PIL 保存，链路最短、最可控。

用法：
    from uecap import find_hwnd, capture
    hwnd = find_hwnd()           # 按进程名找 UnrealEditor 主窗口
    img = capture(hwnd)          # PIL.Image
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from PIL import Image

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

# 声明 DPI 感知，必须在任何窗口查询之前
try:
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))   # PER_MONITOR_AWARE_V2
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


def find_hwnd(process_name: str = "UnrealEditor.exe") -> int:
    """按进程名找主窗口句柄（取第一个可见、尺寸最大的）。"""
    target_pids = _pids_of(process_name)
    found: list[tuple[int, int, int]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enum_proc(hwnd, _lparam):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in target_pids and user32.IsWindowVisible(hwnd):
            rect = RECT()
            if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                w = rect.right - rect.left
                h = rect.bottom - rect.top
                if w > 400 and h > 300:
                    found.append((w * h, hwnd, pid.value))
        return True

    user32.EnumWindows(enum_proc, 0)
    if not found:
        raise RuntimeError("找不到 %s 的主窗口" % process_name)

    # 不能只按面积取最大：编辑器会另开"消息日志""大纲"等子窗口，
    # 它们可能比主窗口还大。按标题优先取主窗口。
    titled = []
    for _area, hwnd, _pid in found:
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        title = buf.value
        if "GramStain" in title or "虚幻编辑器" in title or "Unreal Editor" in title:
            titled.append((_area, hwnd))
    if titled:
        titled.sort(reverse=True)
        return titled[0][1]

    found.sort(reverse=True)
    return found[0][1]


def _pids_of(process_name: str) -> set[int]:
    """用 tasklist 取进程名对应的 PID 集合（不引入 psutil 依赖）。"""
    import subprocess

    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq %s" % process_name, "/FO", "CSV", "/NH"],
                         capture_output=True, text=True, errors="ignore").stdout
    pids = set()
    for line in out.splitlines():
        parts = line.strip().strip('"').split('","')
        if len(parts) >= 2 and parts[1].strip('"').isdigit():
            pids.add(int(parts[1].strip('"')))
    return pids


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    rect = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def capture(hwnd: int) -> Image.Image:
    """PrintWindow 抓取整窗口，返回 RGB 图像。"""
    left, top, right, bottom = window_rect(hwnd)
    w, h = right - left, bottom - top
    if w <= 0 or h <= 0:
        raise RuntimeError("窗口尺寸无效")

    hdc_window = user32.GetWindowDC(hwnd)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_window)
    hbmp = gdi32.CreateCompatibleBitmap(hdc_window, w, h)
    gdi32.SelectObject(hdc_mem, hbmp)

    # flag=2 即 PW_RENDERFULLCONTENT，D3D 渲染的窗口必须用它
    user32.PrintWindow(hwnd, hdc_mem, 2)

    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h          # 负数表示自上而下
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0      # BI_RGB

    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(hdc_mem, hbmp, 0, h, buf, ctypes.byref(bmi), 0)

    img = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")

    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(hwnd, hdc_window)
    return img


if __name__ == "__main__":
    h = find_hwnd()
    print("hwnd=%s rect=%s" % (h, window_rect(h)))
    im = capture(h)
    im.save(r"E:\UI\.uni-shot\ue-capture\_ctypes_test.png")
    print("saved %dx%d" % im.size)
