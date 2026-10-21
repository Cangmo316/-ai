"""合并数据并切分训练 / 评测集。

## 清洗三件事

1. **去重**：用户侧语句归一化后重复的直接丢（同义重复会让模型过拟合到那几句）
2. **脱敏复检**：合成数据里也可能混进手机号/编号，入口再抹一遍
3. **切分**：按 9:1 切，且**评测集按场景分类分层抽样**，
   避免评测集全落在某一类（那样看不出模型在别的类别上退化）

用法：
    python scripts/clean_split.py
输出：
    data/final/train.jsonl
    data/final/eval.jsonl
    data/final/stats.json
"""

from __future__ import annotations

import json
import random
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "data" / "seed" / "seed.jsonl"
SYNTH = ROOT / "data" / "synth" / "synth.jsonl"
OUT = ROOT / "data" / "final"

SCRUB = [
    (re.compile(r"1[3-9]\d{9}"), "[电话]"),
    (re.compile(r"\d{17}[\dXx]"), "[身份证]"),
    (re.compile(r"\d{6,}"), "[编号]"),
]


def norm(text: str) -> str:
    """归一化用于判重：去空白与标点。"""
    return re.sub(r"[^\u4e00-\u9fffa-zA-Z0-9]", "", text or "").lower()


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
        if line:
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    seed = load(SEED)
    synth = load(SYNTH)
    print("  种子 %d 条，合成 %d 条" % (len(seed), len(synth)))

    merged: list[dict] = []
    seen: set[str] = set()
    dropped_dup = 0
    for row in seed + synth:
        messages = row.get("messages") or []
        if len(messages) < 3:
            continue
        user = scrub(messages[1].get("content", ""))
        assistant = scrub(messages[2].get("content", ""))
        if len(user) < 2 or len(assistant) < 10:
            continue
        key = norm(user)[:24]
        if key in seen:
            dropped_dup += 1
            continue
        seen.add(key)
        messages[1]["content"] = user
        messages[2]["content"] = assistant
        merged.append(row)

    print("  去重丢弃 %d 条，保留 %d 条" % (dropped_dup, len(merged)))

    # 分层抽样：按 meta.group / meta.persona 分组，保证每类都有评测样本
    buckets: dict[str, list[dict]] = defaultdict(list)
    for row in merged:
        meta = row.get("meta") or {}
        key = meta.get("group") or meta.get("persona") or "default"
        buckets[key].append(row)

    random.seed(20261018)
    train: list[dict] = []
    evaluate: list[dict] = []
    for key, items in buckets.items():
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

    def chars(rows: list[dict]) -> int:
        return sum(
            len(r["messages"][1]["content"]) + len(r["messages"][2]["content"]) for r in rows
        )

    stats = {
        "seed": len(seed),
        "synth": len(synth),
        "merged": len(merged),
        "dropped_dup": dropped_dup,
        "train": len(train),
        "eval": len(evaluate),
        "train_chars": chars(train),
        "eval_chars": chars(evaluate),
        "buckets": {k: len(v) for k, v in buckets.items()},
    }
    (OUT / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n=== 最终数据集 ===")
    print("  训练集 : %3d 条 / %5d 字" % (len(train), stats["train_chars"]))
    print("  评测集 : %3d 条 / %5d 字" % (len(evaluate), stats["eval_chars"]))
    print("  分类分布:")
    for key, count in sorted(stats["buckets"].items(), key=lambda x: -x[1]):
        print("    %-12s %d" % (key, count))
    print("  输出   : %s" % OUT)


if __name__ == "__main__":
    main()
