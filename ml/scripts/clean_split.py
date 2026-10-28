"""合并数据并切分：训练 / 评测 / 严格留出。

## 这一轮修的一个方法论错误（重要）

上一轮把 `seed.jsonl`（63 条生产场景 + 优质回复）**同时**当成：
  · 训练数据（90% 进了 train.jsonl）
  · 评测集（eval_lora.py 跑的就是这 63 条）

等于**用训练集测自己**，93.7% 是虚高的。

现在改成：**63 条生产场景全部留出，一条都不进训练**，
写进 `holdout.jsonl` 只用于最终评测。

## 三个输出

  train.jsonl    只含合成数据（普通 + 高危定向），用于训练
  eval.jsonl     从合成数据里分层抽 10%，用于监控过拟合
  holdout.jsonl  63 条生产场景，**评测专用，绝不进训练**

用法：
    python scripts/clean_split.py
"""

from __future__ import annotations

import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = Path(r"E:\比邻AI\server")
sys.path.insert(0, str(SERVER))

SEED = ROOT / "data" / "seed" / "seed.jsonl"
SYNTH = ROOT / "data" / "synth" / "synth.jsonl"
HIGHRISK = ROOT / "data" / "synth" / "highrisk.jsonl"
OUT = ROOT / "data" / "final"

SCRUB = [
    (re.compile(r"1[3-9]\d{9}"), "[电话]"),
    (re.compile(r"\d{17}[\dXx]"), "[身份证]"),
    (re.compile(r"\d{6,}"), "[编号]"),
]


def norm(text: str) -> str:
    """归一化用于判重与留出匹配：去空白与标点。"""
    return re.sub(r"[^\u4e00-\u9fffa-zA-Z0-9]", "", text or "").lower()


def holdout_texts() -> set[str]:
    """63 条生产场景，必须从训练集里剔除。"""
    from tests.scenarios import SCENARIOS

    return {norm(case["text"]) for case in SCENARIOS}


def scrub(text: str) -> str:
    out = text or ""
    for pattern, repl in SCRUB:
        out = pattern.sub(repl, out)
    return out.strip()


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    seed = load(SEED)
    synth = load(SYNTH)
    highrisk = load(HIGHRISK)
    held = holdout_texts()

    print("  种子 %d 条 | 普通合成 %d 条 | 高危定向 %d 条" % (len(seed), len(synth), len(highrisk)))
    print("  留出集（生产场景，绝不进训练）: %d 条" % len(held))

    merged: list[dict] = []
    holdout: list[dict] = []
    seen: set[str] = set()
    dropped_dup = 0

    for row in seed + synth + highrisk:
        messages = row.get("messages") or []
        if len(messages) < 3:
            continue
        user = scrub(messages[1].get("content", ""))
        assistant = scrub(messages[2].get("content", ""))
        if len(user) < 2 or len(assistant) < 10:
            continue

        # 留出：生产场景不进训练（否则评测就是自测）
        if norm(user) in held:
            holdout.append(row)
            continue

        key = norm(user)[:24]
        if key in seen:
            dropped_dup += 1
            continue
        seen.add(key)
        messages[1]["content"] = user
        messages[2]["content"] = assistant
        merged.append(row)

    print("  去重丢弃 %d 条，可训练 %d 条，留出 %d 条" % (dropped_dup, len(merged), len(holdout)))

    # 分层抽样：保证每类都有评测样本
    buckets: dict[str, list[dict]] = defaultdict(list)
    for row in merged:
        meta = row.get("meta") or {}
        key = meta.get("risk") or meta.get("group") or meta.get("persona") or "default"
        buckets[key].append(row)

    random.seed(20261021)
    train: list[dict] = []
    evaluate: list[dict] = []
    for _key, items in buckets.items():
        random.shuffle(items)
        cut = max(1, round(len(items) * 0.1)) if len(items) >= 5 else 0
        evaluate.extend(items[:cut])
        train.extend(items[cut:])

    random.shuffle(train)
    random.shuffle(evaluate)

    def dump(path: Path, rows: list[dict]) -> None:
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    dump(OUT / "train.jsonl", train)
    dump(OUT / "eval.jsonl", evaluate)
    dump(OUT / "holdout.jsonl", holdout)

    def chars(rows: list[dict]) -> int:
        return sum(
            len(r["messages"][1]["content"]) + len(r["messages"][2]["content"]) for r in rows
        )

    stats = {
        "seed": len(seed),
        "synth": len(synth),
        "highrisk": len(highrisk),
        "holdout": len(holdout),
        "merged": len(merged),
        "dropped_dup": dropped_dup,
        "train": len(train),
        "eval": len(evaluate),
        "train_chars": chars(train),
        "eval_chars": chars(evaluate),
        "holdout_chars": chars(holdout),
        "buckets": {k: len(v) for k, v in buckets.items()},
    }
    (OUT / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n=== 最终数据集 ===")
    print("  训练集 : %4d 条 / %6d 字" % (len(train), stats["train_chars"]))
    print("  评测集 : %4d 条 / %6d 字" % (len(evaluate), stats["eval_chars"]))
    print("  留出集 : %4d 条 / %6d 字（评测专用）" % (len(holdout), stats["holdout_chars"]))
    print("  分类分布:")
    for key, count in sorted(stats["buckets"].items(), key=lambda x: -x[1])[:12]:
        print("    %-14s %d" % (key, count))
    print("  输出   : %s" % OUT)


if __name__ == "__main__":
    main()
