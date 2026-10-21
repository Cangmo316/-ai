"""从 ModelScope 下载基座模型（直连 HTTP，不依赖 modelscope SDK）。

## 为什么不用 SDK

SDK 会装一堆依赖，而且默认缓存路径要额外配。这里只需 6 个文件，
直接用 ModelScope 的 repo 接口下，落盘位置完全可控（必须在 E 盘，C 只剩 20GB）。

## 为什么选 Qwen2.5-1.5B-Instruct

  · 8GB 显存下 LoRA 微调够用（bf16 权重约 3.1GB）
  · 中文口语底子好，是"学说话方式"而不是学知识，1.5B 够
  · 如果显存吃紧可以换 0.5B（改 --model）

用法：
    python scripts/download_model.py
    python scripts/download_model.py --model Qwen/Qwen2.5-0.5B-Instruct
输出：
    E:\\比邻AI\\ml\\models\\<模型名>\\
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"

# 只下推理与训练必需的
WANTED = (
    "config.json",
    "generation_config.json",
    "merges.txt",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
)

API_FILES = "https://www.modelscope.cn/api/v1/models/{model}/repo/files?Revision=master&Recursive=true"
API_RAW = "https://www.modelscope.cn/api/v1/models/{model}/repo?Revision=master&FilePath={path}"


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return "%.1f %s" % (n, unit)
        n /= 1024
    return "%.1f TB" % n


def list_files(model: str) -> list[dict]:
    with urllib.request.urlopen(API_FILES.format(model=model), timeout=60) as response:
        data = json.loads(response.read().decode("utf-8"))
    files = (data.get("Data") or {}).get("Files") or []
    return files


def download(model: str, path: str, target: Path) -> bool:
    """带断点续传的单文件下载。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    have = target.stat().st_size if target.exists() else 0
    url = API_RAW.format(model=model, path=urllib.parse.quote(path))
    request = urllib.request.Request(url)
    request.add_header("User-Agent", "Mozilla/5.0")
    if have:
        request.add_header("Range", "bytes=%d-" % have)
    try:
        response = urllib.request.urlopen(request, timeout=60)
    except Exception as exc:  # noqa: BLE001
        print("    打不开：%s" % exc)
        return False

    total = int(response.headers.get("Content-Length") or 0) + have
    mode = "ab" if have else "wb"
    written = have
    started = time.time()
    last = 0.0
    with target.open(mode) as handle:
        while True:
            chunk = response.read(1024 * 128)
            if not chunk:
                break
            handle.write(chunk)
            written += len(chunk)
            now = time.time()
            if now - last > 3:
                last = now
                speed = (written - have) / max(now - started, 0.001)
                print("      %s / %s  %.2f MB/s" % (human(written), human(total), speed / 1024 / 1024), flush=True)
    response.close()
    ok = total == 0 or target.stat().st_size >= total
    return ok


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="Qwen/Qwen2.5-1.5B-Instruct")
    args = parser.parse_args()

    short = args.model.split("/")[-1]
    out = MODELS / short
    print("  模型：%s" % args.model)
    print("  落盘：%s" % out)

    files = list_files(args.model)
    if not files:
        print("  拿不到文件列表，检查模型名或网络")
        return

    picked = []
    for item in files:
        path = item.get("Path") or item.get("Name") or ""
        if path in WANTED:
            picked.append((path, int(item.get("Size") or 0)))

    # 有些仓库是分片 safetensors，按索引文件把分片也算进来
    index = [p for p, _s in picked if p == "model.safetensors.index.json"]
    for item in files:
        path = item.get("Path") or ""
        if path.startswith("model-") and path.endswith(".safetensors"):
            picked.append((path, int(item.get("Size") or 0)))

    seen: set[str] = set()
    picked = [(p, s) for p, s in picked if not (p in seen or seen.add(p))]

    if not picked:
        print("  没有匹配到需要的文件")
        return

    total = sum(s for _p, s in picked)
    print("  需要 %d 个文件，合计 %s\n" % (len(picked), human(total)))

    failed = []
    for path, size in picked:
        target = out / path
        if target.exists() and target.stat().st_size >= size > 0:
            print("  [跳过] %s（已完整）" % path)
            continue
        print("  [下载] %s  %s" % (path, human(size)))
        if not download(args.model, path, target):
            failed.append(path)

    print("\n=== 结果 ===")
    for path, _size in picked:
        target = out / path
        mark = "OK" if target.exists() else "缺"
        print("  %-28s %-4s %s" % (path, mark, human(target.stat().st_size) if target.exists() else "-"))
    if failed:
        print("  失败：%s" % ", ".join(failed))
    else:
        print("  全部就绪：%s" % out)


if __name__ == "__main__":
    main()
