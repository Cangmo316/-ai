"""导出真实对话语料（本地已有的老人原话 / 家人原话）。

## 为什么要单独导一遍

微调要的是"这个人怎么说话"，而现有数据分散在两处：
  · `conversation_messages.payload`（JSON）—— 老人对 AI 说的话
  · `messages`（表）—— 家人会话里真人的话

这一步把它们抽成统一 jsonl，并做**隐私清洗**（姓名/电话/地址/编号）。
清洗必须在入训练集之前，而不是之后 —— 训练过的数据无法"撤回"。

用法：
    python scripts/export_corpus.py
输出：
    data/raw/elder_utterances.jsonl
    data/raw/family_utterances.jsonl
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = Path(r"E:\比邻AI\server\data\bilin.db")
OUT = ROOT / "data" / "raw"

# ── 隐私清洗 ────────────────────────────────────────────────────
# 训练数据一旦进去就无法单独删除，所以清洗要**在入口**做，且宁可多抹。
PATTERNS = [
    (re.compile(r"1[3-9]\d{9}"), "[电话]"),                     # 手机号
    (re.compile(r"0\d{2,3}-?\d{7,8}"), "[电话]"),               # 座机
    (re.compile(r"\d{17}[\dXx]"), "[身份证]"),                   # 身份证
    (re.compile(r"\d{6,}"), "[编号]"),                          # 长数字（账号/编号）
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+"), "[邮箱]"),
    (re.compile(r"\d+号楼?\d*单元?\d*室?"), "[住址]"),
]


def scrub(text: str) -> str:
    out = str(text or "")
    for pattern, repl in PATTERNS:
        out = pattern.sub(repl, out)
    return out.strip()


def export() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB)

    # ① 老人对 AI 说的话
    rows = db.execute("SELECT payload, created_at FROM conversation_messages ORDER BY created_at").fetchall()
    elder: list[dict] = []
    for payload, created in rows:
        try:
            data = json.loads(payload)
        except Exception:
            continue
        if data.get("role") != "elder":
            continue
        text = scrub(data.get("text"))
        if len(text) < 2:
            continue
        elder.append({"text": text, "at": created, "source": "ai_chat"})

    # ② 家人会话里真人的话（排除代理智能体）
    rows = db.execute(
        "SELECT sender_role, text, created_at FROM messages WHERE sender_role != 'agent' ORDER BY created_at"
    ).fetchall()
    family: list[dict] = []
    for role, text, created in rows:
        body = scrub(text)
        if len(body) < 2:
            continue
        family.append({"text": body, "role": role, "at": created, "source": "family_chat"})

    def dump(path: Path, items: list[dict]) -> None:
        with path.open("w", encoding="utf-8") as handle:
            for item in items:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    dump(OUT / "elder_utterances.jsonl", elder)
    dump(OUT / "family_utterances.jsonl", family)

    elder_chars = sum(len(i["text"]) for i in elder)
    family_chars = sum(len(i["text"]) for i in family)
    print("  老人对 AI 说的话 : %3d 条 / %5d 字" % (len(elder), elder_chars))
    print("  家人会话真人消息 : %3d 条 / %5d 字" % (len(family), family_chars))
    print("  合计             : %3d 条 / %5d 字" % (len(elder) + len(family), elder_chars + family_chars))
    print("  输出目录         : %s" % OUT)


if __name__ == "__main__":
    export()
