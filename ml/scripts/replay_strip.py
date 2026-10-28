"""离线回放：把微调模型的 63 条回复过一遍 strip，量化能修掉多少。

## 为什么用回放而不是重跑模型

重跑要 7 分钟且结果有随机性；而 strip 是**纯确定性函数**，
把已有回复过一遍就能算出"加上代码兜底后"的确切效果。
关键是要同时看两面：

  · 真正该剥的，剥掉几条
  · **不该剥的，有没有被误剥**（这一面更重要）
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SERVER = Path(r"E:\比邻AI\server")
sys.path.insert(0, str(SERVER))

from app.persona.prompts import (  # noqa: E402
    has_clinical_content,
    is_medical_question,
    strip_medical_notice,
)

P = Path(r"E:\比邻AI\ml\out\eval_samples.jsonl")

# 这些情况下"提医生"是对的（与 analyze_notice_precision 同一口径）
ESCALATION_OK = [
    ("自伤风险", r"不想活|活不下去|活着没意思|轻生|想死"),
    ("认知信号", r"找不到东西|老忘|记不住|忘了关|认错|糊涂|迷路"),
    ("跌倒外伤", r"摔|跌|磕|碰伤|崴"),
    ("躯体症状", r"疼|晕|麻|闷|喘|血|发烧|吐|拉肚子|睡不着|吃不下|瘦了"),
    ("用药相关", r"吃药|用药|药片|剂量|停药|换药|保健品|偏方|推销"),
    ("照护异常", r"不愿.{0,3}洗|洗澡|不睡|到处走|发脾气|发火|打人|不肯吃|穿衣"),
]


def justified(user: str) -> str:
    for name, pattern in ESCALATION_OK:
        if re.search(pattern, user):
            return name
    return ""


def main() -> None:
    rows = [json.loads(line) for line in P.read_text(encoding="utf-8").splitlines() if line.strip()]
    ft = [r for r in rows if r["tag"] == "ft"]
    print("  微调回复数: %d" % len(ft))

    before_over, after_over = [], []
    mis_stripped = []
    changed = 0

    for row in ft:
        user, reply = row["user"], row["reply"]
        medical = is_medical_question(user) or has_clinical_content(reply)
        after = strip_medical_notice(reply, medical, user)
        if after != reply:
            changed += 1

        # 剥之前的"多余免责"
        if not row["medical"] and row["has_notice"] and not justified(user):
            before_over.append(user)
        # 剥之后还有没有
        still = "医生" in after or "医院" in after or "医嘱" in after
        if not medical and still and not justified(user):
            after_over.append(user)

        # 误剥检查：该保留医生建议的，剥完是否没了
        if justified(user) and ("医生" in reply or "医院" in reply):
            if not ("医生" in after or "医院" in after or "医嘱" in after):
                mis_stripped.append((user, justified(user), reply, after))

    print("  实际被改动的回复: %d 条" % changed)
    print()
    print("  ── 真正多余的免责 ──")
    print("    剥之前: %d 条" % len(before_over))
    for u in before_over:
        print("      · %s" % u)
    print("    剥之后: %d 条  %s" % (len(after_over), "✅ 全部修掉" if not after_over else "⚠️ 仍有残留"))
    for u in after_over:
        print("      · %s" % u)
    print()
    print("  ── 误剥检查（该保留的医生建议有没有被剥掉）──")
    if mis_stripped:
        print("    ⚠️ %d 条被误剥：" % len(mis_stripped))
        for user, reason, before, after in mis_stripped:
            print("      · [%s] %s" % (reason, user))
            print("        剥前: %s" % before.replace("\n", " / ")[:70])
            print("        剥后: %s" % after.replace("\n", " / ")[:70])
    else:
        print("    ✅ 0 条误剥（自伤/认知/跌倒/用药的医生建议都保住了）")


if __name__ == "__main__":
    main()
