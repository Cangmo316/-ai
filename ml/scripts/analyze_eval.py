"""分析评测结果：残留问题 + 免责分布 + 风格样本对照。"""
import json
from pathlib import Path

P = Path(r"E:\比邻AI\ml\out\eval_samples.jsonl")
rows = [json.loads(l) for l in P.read_text(encoding="utf-8").splitlines() if l.strip()]
base = [r for r in rows if r["tag"] == "base"]
ft = [r for r in rows if r["tag"] == "ft"]

print("=== 微调后仍不合格的 %d 条 ===" % sum(1 for r in ft if r["issues"]))
for r in ft:
    if not r["issues"]:
        continue
    print("\n[%s] %s" % (r["group"], r["user"]))
    print("  问题: %s" % "；".join(r["issues"]))
    print("  回复: %s" % r["reply"].replace("\n", " / "))

print("\n=== 免责使用是否合理 ===")
for tag, data in (("基座", base), ("微调", ft)):
    med = [r for r in data if r["medical"]]
    dai = [r for r in data if not r["medical"]]
    med_notice = sum(1 for r in med if r["has_notice"])
    dai_notice = sum(1 for r in dai if r["has_notice"])
    print("  %s: 医疗类 %d 条中 %d 条带免责；日常类 %d 条中 %d 条误加免责"
          % (tag, len(med), med_notice, len(dai), dai_notice))

print("\n=== 风格对照（同一句话，两个模型）===")
pairs = 0
for b in base:
    f = next((x for x in ft if x["user"] == b["user"]), None)
    if not f:
        continue
    if b["user"] not in (
        "今天天气不错，我出去走了走",
        "我在厕所摔了一跤，现在能站起来",
        "我晚上老是睡不好，翻来覆去的",
        "儿媳妇老嫌我做得不好，我心里难受",
    ):
        continue
    pairs += 1
    print("\n老人：%s" % b["user"])
    print("  基座（%d 行，均 %.0f 字/行）：%s" % (b["lines"], b["avg_line"], b["reply"].replace("\n", " / ")))
    print("  微调（%d 行，均 %.0f 字/行）：%s" % (f["lines"], f["avg_line"], f["reply"].replace("\n", " / ")))
