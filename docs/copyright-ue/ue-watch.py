"""静默监听 UE 窗口：人手动点击后，自动把变化的画面存下来。

为什么需要"人点、我抓"：这台机器上合成的鼠标/键盘事件点不动 UE 的 UMG 模式按钮
（窗口置前、移位点击、双击、MOUSEMOVE 注入、键盘导航都试过，只有真实交互生效）。

做法：每 2.5 秒 PrintWindow 抓一次主窗口（不动焦点），只比较 PIE 视口区域，
与基线差异超过阈值就落盘，最多存 max_frames 张。

用法：
    python ue-watch.py --seconds 300 --tag story
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from PIL import Image, ImageChops

from uecap import capture, find_hwnd

OUT = Path(r"E:\UI\.uni-shot\ue-capture")
VIEWPORT = (6, 192, 1150, 817)      # 1600x960 窗口里的 PIE 视口


def viewport_gray(img: Image.Image) -> Image.Image:
    crop = img.crop(VIEWPORT).convert("L").resize((286, 156))
    return crop


def mean_diff(a: Image.Image, b: Image.Image) -> float:
    diff = ImageChops.difference(a, b)
    hist = diff.histogram()
    total = sum(hist)
    if not total:
        return 0.0
    return sum(i * n for i, n in enumerate(hist)) / total * 255.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=300)
    ap.add_argument("--tag", default="story")
    ap.add_argument("--threshold", type=float, default=6.0)
    ap.add_argument("--max-frames", type=int, default=8)
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    hwnd = find_hwnd()
    print("WATCHING hwnd=%s for %ds" % (hwnd, args.seconds), flush=True)

    baseline = viewport_gray(capture(hwnd))
    baseline.save(OUT / ("%s-baseline.png" % args.tag))

    deadline = time.time() + args.seconds
    saved = 0
    last = 0.0
    while time.time() < deadline:
        time.sleep(2.5)
        try:
            img = capture(hwnd)
        except Exception as exc:
            print("capture error: %s" % exc, flush=True)
            continue

        cur = viewport_gray(img)
        d = mean_diff(baseline, cur)
        last = d
        if d > args.threshold:
            saved += 1
            name = "%s-%02d.png" % (args.tag, saved)
            img.save(OUT / name)
            print("CHANGED diff=%.2f saved %s" % (d, name), flush=True)
            if saved >= args.max_frames:
                print("reached max frames", flush=True)
                break

    print("WATCH END saved=%d lastdiff=%.2f" % (saved, last), flush=True)


if __name__ == "__main__":
    main()
