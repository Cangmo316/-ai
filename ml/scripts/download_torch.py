"""下载 torch CUDA 轮子（带断点续传）。

为什么不直接用 pip：阿里云的 pytorch-wheels 镜像对直链要求
`Referer` 与 `User-Agent`，缺任一返回 403；而 pip 不会带这两个头。
所以先用本脚本把轮子拉到本地，再 `pip install <本地文件>`。
"""

from __future__ import annotations

import os
import sys
import time
import urllib.request
from pathlib import Path

BASE = "https://mirrors.aliyun.com/pytorch-wheels/cu124/"
NAME = "torch-2.6.0%2Bcu124-cp313-cp313-win_amd64.whl"
OUT = Path(r"E:\比邻AI\ml\wheels")
LOCAL = OUT / "torch-2.6.0+cu124-cp313-cp313-win_amd64.whl"


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return "%.1f %s" % (n, unit)
        n /= 1024
    return "%.1f TB" % n


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    url = BASE + NAME

    have = LOCAL.stat().st_size if LOCAL.exists() else 0
    request = urllib.request.Request(url)
    request.add_header("Referer", BASE)
    request.add_header("User-Agent", "Mozilla/5.0")
    if have:
        request.add_header("Range", "bytes=%d-" % have)
        print("  断点续传，从 %s 继续" % human(have))

    try:
        response = urllib.request.urlopen(request, timeout=60)
    except Exception as exc:  # noqa: BLE001
        print("  打不开：%s" % exc)
        return 1

    total = response.headers.get("Content-Range", "")
    size = int(total.split("/")[-1]) if "/" in total else int(response.headers.get("Content-Length") or 0)
    print("  总大小：%s" % human(size))

    mode = "ab" if have else "wb"
    written = have
    started = time.time()
    last = 0.0
    with LOCAL.open(mode) as handle:
        while True:
            chunk = response.read(1024 * 256)
            if not chunk:
                break
            handle.write(chunk)
            written += len(chunk)
            now = time.time()
            if now - last > 5:
                last = now
                speed = (written - have) / max(now - started, 0.001)
                pct = 100.0 * written / size if size else 0
                print(
                    "  %5.1f%%  %s / %s  %.2f MB/s"
                    % (pct, human(written), human(size), speed / 1024 / 1024),
                    flush=True,
                )
    response.close()

    ok = size == 0 or LOCAL.stat().st_size >= size
    print("  完成：%s  校验：%s" % (human(LOCAL.stat().st_size), "OK" if ok else "大小不符"))
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
